"""Upload para YouTube Shorts via YouTube Data API v3 (OAuth).

Vídeos verticais de até 3 minutos são classificados automaticamente como Shorts.
"""
from __future__ import annotations

import json
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .. import config

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_FILE = config.TOKENS_DIR / "youtube.json"
REDIRECT = f"{config.PUBLIC_BASE_URL}/auth/youtube/callback"


def _flow(state: str | None = None) -> Flow:
    if not config.YOUTUBE_CLIENT_SECRET_FILE.exists():
        raise RuntimeError(f"Arquivo OAuth do Google não encontrado: {config.YOUTUBE_CLIENT_SECRET_FILE}")
    return Flow.from_client_secrets_file(str(config.YOUTUBE_CLIENT_SECRET_FILE), scopes=SCOPES, state=state, redirect_uri=REDIRECT)


def auth_url() -> str:
    flow = _flow()
    url, state = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true")
    (config.TOKENS_DIR / "youtube_state.json").write_text(
        json.dumps({"state": state, "code_verifier": getattr(flow, "code_verifier", None)})
    )
    return url


def handle_callback(full_url: str) -> None:
    saved = json.loads((config.TOKENS_DIR / "youtube_state.json").read_text())
    flow = _flow(saved["state"])
    if saved.get("code_verifier"):
        flow.code_verifier = saved["code_verifier"]
    if config.PUBLIC_BASE_URL.startswith("http://"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # apenas para uso local
    flow.fetch_token(authorization_response=full_url)
    TOKEN_FILE.write_text(flow.credentials.to_json())


def is_connected() -> bool:
    return TOKEN_FILE.exists()


def _creds() -> Credentials:
    if not TOKEN_FILE.exists():
        raise RuntimeError("YouTube não conectado. Abra /auth/youtube para autorizar.")
    creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        TOKEN_FILE.write_text(creds.to_json())
    return creds


def upload(video_path: str, title: str, description: str, tags: list[str], privacy: str | None = None) -> dict:
    yt = build("youtube", "v3", credentials=_creds(), cache_discovery=False)
    if "#shorts" not in (title + description).lower():
        description = f"{description}\n\n#Shorts"
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": "22",
        },
        "status": {
            "privacyStatus": privacy or config.YOUTUBE_PRIVACY,
            "selfDeclaredMadeForKids": False,
        },
    }
    media = MediaFileUpload(video_path, mimetype="video/mp4", chunksize=8 * 1024 * 1024, resumable=True)
    req = yt.videos().insert(part="snippet,status", body=body, media_body=media)
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]
    return {"id": vid, "url": f"https://youtube.com/shorts/{vid}"}
