"""Config file shared by the CLI and the VS Code extension.

    ~/.config/mogi/config.json   (override with $MOGI_CONFIG)
    {
      "site": "https://….cloudfront.net",
      "token": "<bearer token from `mogi login`>",
      "login": "shiroyang",
      "workspace": "~/mogi"
    }
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULT_SITE = "https://mogi-judge.vercel.app"
DEFAULT_WORKSPACE = "~/mogi"


def config_path() -> Path:
    env = os.environ.get("MOGI_CONFIG")
    if env:
        return Path(env).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "mogi" / "config.json"


def load() -> dict:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("site", DEFAULT_SITE)
    data.setdefault("workspace", DEFAULT_WORKSPACE)
    return data


def save(data: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)  # the token inside is a credential
    tmp.replace(path)
    return path


def workspace(cfg: dict) -> Path:
    return Path(cfg.get("workspace") or DEFAULT_WORKSPACE).expanduser()
