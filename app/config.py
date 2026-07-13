"""App configuration (env-overridable).

APP_DEBUG   "1"/"0" — enables JS console debug messages (default on for local
            use; set APP_DEBUG=0 in production to silence the console). File
            logs are always written regardless.
APP_LOG_DIR path to the log directory (default: <project>/logs).
"""
from __future__ import annotations

import os
from pathlib import Path

DEBUG = os.getenv("APP_DEBUG", "1").strip().lower() not in ("0", "false", "no", "")

_default_log_dir = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR = Path(os.getenv("APP_LOG_DIR") or _default_log_dir)
