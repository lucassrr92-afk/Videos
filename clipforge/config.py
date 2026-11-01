"""Configuração central lida do ambiente (.env)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", ROOT / "data"))
JOBS_DIR = DATA_DIR / "jobs"
TOKENS_DIR = Path(os.getenv("TOKENS_DIR", ROOT / "tokens"))
FONTS_DIR = ROOT / "fonts"

for _d in (JOBS_DIR, TOKENS_DIR, FONTS_DIR):
    _d.mkdir(parents=True, exist_ok=True)


def env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


ANTHROPIC_API_KEY = env("ANTHROPIC_API_KEY")
CLAUDE_MODEL = env("CLAUDE_MODEL", "claude-opus-5-5")

WHISPER_MODEL = env("WHISPER_MODEL", "small")
WHISPER_DEVICE = env("WHISPER_DEVICE", "auto")
WHISPER_LANGUAGE = env("WHISPER_LANGUAGE") or None

PUBLIC_BASE_URL = env("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")

YOUTUBE_CLIENT_SECRET_FILE = Path(env("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json"))
if not YOUTUBE_CLIENT_SECRET_FILE.is_absolute():
    YOUTUBE_CLIENT_SECRET_FILE = ROOT / YOUTUBE_CLIENT_SECRET_FILE
YOUTUBE_PRIVACY = env("YOUTUBE_PRIVACY", "public")

TIKTOK_CLIENT_KEY = env("TIKTOK_CLIENT_KEY")
TIKTOK_CLIENT_SECRET = env("TIKTOK_CLIENT_SECRET")
TIKTOK_PRIVACY = env("TIKTOK_PRIVACY", "PUBLIC_TO_EVERYONE")

IG_USER_ID = env("IG_USER_ID")
IG_ACCESS_TOKEN = env("IG_ACCESS_TOKEN")
IG_GRAPH_VERSION = env("IG_GRAPH_VERSION", "v21.0")
META_APP_ID = env("META_APP_ID")
META_APP_SECRET = env("META_APP_SECRET")

# Acesso ao app web (uso pessoal): defina uma senha ao hospedar na internet
APP_PASSWORD = env("APP_PASSWORD")
MAX_UPLOAD_MB = int(env("MAX_UPLOAD_MB", "4096"))

# Saída vertical padrão para Shorts / TikTok / Reels
OUT_W, OUT_H, OUT_FPS = 1080, 1920, 30
