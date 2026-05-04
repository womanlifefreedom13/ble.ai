"""
LiveKit token helper.

Modes (set via cfg["token_mode"]):

  "preset"    — read pre-configured tokens from settings.json or a file/env-var
                reference. The recommended mode for Bale.ai today, since Bale
                does not expose a public guest-token endpoint.

                A token value can be:
                    - the raw JWT string
                    - "@/path/to/file"   → contents of file (whitespace-stripped)
                    - "${ENV_VAR}"       → contents of env var

  "selfhost"  — generate a JWT locally from api_key + api_secret. Use this
                when running your own LiveKit server on the exit VPS.

  "bale_api"  — EXPERIMENTAL. Speculative call to a Bale meeting API. Likely
                does NOT work; kept as a placeholder. Use "preset" instead.

How to get a Bale.ai token (manual extraction):
    1. Open meet.bale.ai in a desktop browser, sign in.
    2. Create or join a meeting; note the meeting ID (room name).
    3. Open DevTools → Network tab. Filter by "join" or "token".
    4. The request to LiveKit's signal server will include a JWT in the URL
       (?access_token=…) or in a JSON response body. Copy that JWT.
    5. Repeat from a SECOND browser/incognito window with a different account
       to get the second token (entry vs. exit need different identities).
    6. Paste both into settings.json as entry_token and exit_token.
"""

import logging
import os
import time

logger = logging.getLogger(__name__)


def _resolve_token_value(raw: str) -> str:
    """Resolve a token reference (@file or ${ENV}) or pass through a literal."""
    if not raw:
        return raw
    if raw.startswith("@"):
        path = raw[1:]
        with open(path) as f:
            return f.read().strip()
    if raw.startswith("${") and raw.endswith("}"):
        var = raw[2:-1]
        val = os.environ.get(var)
        if not val:
            raise ValueError(f"Env var {var} is not set or is empty")
        return val.strip()
    return raw.strip()


def _warn_if_expiring(token: str) -> None:
    """Best-effort: log a warning if the JWT expires within 24h or is already expired."""
    try:
        import base64
        import json

        parts = token.split(".")
        if len(parts) != 3:
            return
        # Add padding for urlsafe_b64decode
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        exp = payload.get("exp")
        if not exp:
            return
        now = time.time()
        remaining = exp - now
        if remaining <= 0:
            logger.error("LiveKit JWT already expired %.0f seconds ago — refresh it!", -remaining)
        elif remaining < 86400:
            logger.warning("LiveKit JWT expires in %.1f hours — plan a refresh", remaining / 3600)
        else:
            logger.debug("LiveKit JWT valid for %.1f hours", remaining / 3600)
    except Exception:
        pass


async def get_token(cfg: dict, role: str) -> str:
    """
    Return a LiveKit JWT for the given role ("entry" or "exit").

    role maps to cfg keys:
        entry -> cfg["entry_token"]
        exit  -> cfg["exit_token"]
    """
    mode = cfg.get("token_mode", "preset")

    if mode == "preset":
        key = f"{role}_token"
        raw = cfg.get(key, "")
        if not raw:
            raise ValueError(
                f"token_mode=preset but '{key}' is missing from config. "
                f"See bale_token.py docstring for how to obtain a Bale token."
            )
        token = _resolve_token_value(raw)
        if not token:
            raise ValueError(f"Resolved '{key}' is empty")
        _warn_if_expiring(token)
        return token

    if mode == "selfhost":
        token = _generate_selfhost_token(cfg, role)
        _warn_if_expiring(token)
        return token

    if mode == "bale_api":
        logger.warning(
            "token_mode=bale_api is experimental and likely non-functional. "
            "Use 'preset' with manually-extracted tokens instead."
        )
        return await _get_bale_guest_token(cfg, role)

    raise ValueError(f"Unknown token_mode: {mode!r}")


async def _get_bale_guest_token(cfg: dict, role: str) -> str:
    """Speculative request to a Bale meeting API. Likely won't work."""
    try:
        import aiohttp
    except ImportError:
        raise ImportError("aiohttp required: pip install aiohttp")

    room_name = cfg["room_name"]
    identity = f"tunnel-{role}"
    url = cfg.get("bale_api_url", "https://meet.bale.ai/api/join-room")

    async with aiohttp.ClientSession() as session:
        async with session.post(
            url,
            json={"roomName": room_name, "identity": identity, "name": identity},
            timeout=aiohttp.ClientTimeout(total=15),
        ) as r:
            if r.status != 200:
                body = await r.text()
                raise RuntimeError(f"Bale API returned HTTP {r.status}: {body[:200]}")
            data = await r.json(content_type=None)

    token = data.get("token") or data.get("accessToken") or data.get("jwt")
    if not token:
        raise RuntimeError(f"Could not find token in Bale API response: {list(data.keys())}")
    return token


def _generate_selfhost_token(cfg: dict, role: str) -> str:
    """Generate a LiveKit JWT for a self-hosted server."""
    try:
        from livekit.api import AccessToken, VideoGrants
    except ImportError:
        raise ImportError("livekit-api required for selfhost mode: pip install livekit-api")

    api_key = cfg.get("api_key")
    api_secret = cfg.get("api_secret")
    if not api_key or not api_secret:
        raise ValueError("token_mode=selfhost requires 'api_key' and 'api_secret' in config")

    room_name = cfg["room_name"]
    identity = f"tunnel-{role}"
    ttl_hours = int(cfg.get("token_ttl_hours", 24 * 7))

    grants = VideoGrants(room_join=True, room=room_name)
    return (
        AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_name(identity)
        .with_ttl(ttl_hours * 3600)
        .with_grants(grants)
        .to_jwt()
    )
