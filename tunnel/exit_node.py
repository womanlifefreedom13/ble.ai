"""
Exit node — free-internet side.

Joins the LiveKit room, listens for framed tunnel messages.
For each CONNECT frame: opens a real TCP connection to the target host.
Forwards DATA frames to the TCP socket and pumps responses back as DATA frames.
"""

import asyncio
import logging
import socket

from livekit import rtc

from .protocol import (
    MSG_CONNECT, MSG_DATA, MSG_CLOSE,
    decode_frame, decode_connect,
    encode_connected, encode_data, encode_close,
    MAX_PAYLOAD,
)
from .bale_token import get_token

logger = logging.getLogger(__name__)

_tasks: set = set()


def _spawn(coro):
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return t


_tcp_writers: dict = {}   # stream_id -> asyncio.StreamWriter (to target)
_tcp_tasks: dict = {}     # stream_id -> asyncio.Task (pump task)

_room: rtc.Room | None = None
_cfg: dict = {}


def _enable_tcp_keepalive(sock: socket.socket) -> None:
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        for opt, val in (("TCP_KEEPIDLE", 60), ("TCP_KEEPINTVL", 30), ("TCP_KEEPCNT", 5)):
            if hasattr(socket, opt):
                sock.setsockopt(socket.IPPROTO_TCP, getattr(socket, opt), val)
    except OSError as e:
        logger.debug("Could not set TCP keepalive: %s", e)


def _cleanup_stream(stream_id: int):
    writer = _tcp_writers.pop(stream_id, None)
    if writer:
        try:
            writer.close()
        except Exception:
            pass
    task = _tcp_tasks.pop(stream_id, None)
    if task and not task.done():
        task.cancel()


def _cleanup_all_streams():
    for sid in list(_tcp_writers):
        _cleanup_stream(sid)


async def _tcp_to_dc_pump(stream_id: int, reader: asyncio.StreamReader):
    """Read from target TCP socket and forward as DATA frames."""
    try:
        while True:
            chunk = await reader.read(MAX_PAYLOAD)
            if not chunk:
                break
            await _room.local_participant.publish_data(
                payload=encode_data(stream_id, chunk), reliable=True,
            )
    except (ConnectionResetError, BrokenPipeError, OSError) as e:
        logger.debug("[%d] Target connection error: %s", stream_id, e)
    except Exception as e:
        logger.warning("[%d] Unexpected pump error: %s", stream_id, e)
    finally:
        _cleanup_stream(stream_id)
        try:
            await _room.local_participant.publish_data(
                payload=encode_close(stream_id), reliable=True,
            )
        except Exception:
            pass
        logger.debug("[%d] Pump ended, CLOSE sent", stream_id)


async def _handle_connect(stream_id: int, host: str, port: int):
    logger.debug("[%d] CONNECT %s:%d", stream_id, host, port)
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=10.0,
        )
    except Exception as e:
        logger.warning("[%d] TCP connect to %s:%d failed: %s", stream_id, host, port, e)
        try:
            await _room.local_participant.publish_data(
                payload=encode_connected(stream_id, False), reliable=True,
            )
        except Exception:
            pass
        return

    sock = writer.get_extra_info("socket")
    if sock is not None:
        _enable_tcp_keepalive(sock)

    _tcp_writers[stream_id] = writer
    _tcp_tasks[stream_id] = _spawn(_tcp_to_dc_pump(stream_id, reader))

    try:
        await _room.local_participant.publish_data(
            payload=encode_connected(stream_id, True), reliable=True,
        )
    except Exception as e:
        logger.warning("[%d] publish_data(CONNECTED) failed: %s", stream_id, e)
        _cleanup_stream(stream_id)
        return

    logger.info("[%d] Tunnel open: %s:%d", stream_id, host, port)


async def _handle_data(stream_id: int, payload: bytes):
    writer = _tcp_writers.get(stream_id)
    if not writer:
        return
    try:
        writer.write(payload)
        if writer.transport.get_write_buffer_size() > 65536:
            await writer.drain()
    except (ConnectionResetError, BrokenPipeError, OSError) as e:
        logger.debug("[%d] Write to target failed: %s", stream_id, e)
        _cleanup_stream(stream_id)


async def _handle_close(stream_id: int):
    logger.debug("[%d] CLOSE received", stream_id)
    _cleanup_stream(stream_id)


def _on_data_received(packet: rtc.DataPacket):
    if packet.participant is None:
        return
    try:
        stream_id, msg_type, payload = decode_frame(packet.data)
    except ValueError as e:
        logger.warning("Malformed frame from %s: %s", packet.participant.identity, e)
        return

    if msg_type == MSG_CONNECT:
        try:
            host, port = decode_connect(payload)
        except Exception as e:
            logger.warning("[%d] Bad CONNECT payload: %s", stream_id, e)
            return
        _spawn(_handle_connect(stream_id, host, port))

    elif msg_type == MSG_DATA:
        _spawn(_handle_data(stream_id, payload))

    elif msg_type == MSG_CLOSE:
        _spawn(_handle_close(stream_id))


async def _connect_with_backoff(room: rtc.Room, url: str, token: str):
    delay = 2.0
    while True:
        try:
            await room.connect(url, token, options=rtc.RoomOptions(auto_subscribe=True))
            logger.info("Connected to LiveKit room: %s", url)
            return
        except Exception as e:
            logger.warning("LiveKit connect failed (%s), retrying in %.0fs", e, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)


async def _on_disconnect(reason):
    logger.warning("LiveKit disconnected (reason=%s), reconnecting...", reason)
    _cleanup_all_streams()
    token = await get_token(_cfg, "exit")
    await _connect_with_backoff(_room, _cfg["livekit_url"], token)


async def run_exit(cfg: dict):
    global _room, _cfg
    _cfg = cfg

    token = await get_token(cfg, "exit")

    _room = rtc.Room()
    _room.on("data_received", _on_data_received)
    _room.on("disconnected", lambda reason: _spawn(_on_disconnect(reason)))

    await _connect_with_backoff(_room, cfg["livekit_url"], token)
    logger.info("Exit node ready — waiting for tunneled connections")

    stop_event = asyncio.Event()
    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        pass
    finally:
        _cleanup_all_streams()
        await _room.disconnect()
