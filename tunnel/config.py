"""
Configuration loader — reads settings.json from a local path or HTTPS URL.
"""

import json
import logging
import urllib.request

logger = logging.getLogger(__name__)

REQUIRED_KEYS = ["livekit_url", "room_name", "socks_port"]


def load_config(path_or_url: str) -> dict:
    """Load and validate config from a local file or an HTTPS URL."""
    if path_or_url.startswith(("http://", "https://")):
        cfg = _fetch_config(path_or_url)
    else:
        with open(path_or_url) as f:
            cfg = json.load(f)
    _validate(cfg)
    return cfg


def _fetch_config(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "tunnel/1.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        body = r.read()
    return json.loads(body)


def _validate(cfg: dict):
    missing = [k for k in REQUIRED_KEYS if k not in cfg]
    if missing:
        raise ValueError(f"Config is missing required keys: {missing}")

    mode = cfg.get("token_mode", "preset")
    if mode == "selfhost":
        for k in ("api_key", "api_secret"):
            if not cfg.get(k):
                raise ValueError(f"token_mode=selfhost requires '{k}' in config")
