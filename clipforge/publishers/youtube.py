"""Upload para YouTube Shorts via YouTube Data API v3 (OAuth por usuário).

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

from .. import accounts, config

SCOPES = ["https://www.googleapis.com/auth/youtube.upload", "https://www.googleapis.com/auth/youtube.readonly"]
REDIRECT = f"{config.PUBLIC_BASE_URL}/auth/youtube/callback"


def _flow(state: str | None = None) -> Flow:
    if not config.YOUTUBE_CLIENT_SECRET_FILE.exists():
        raise RuntimeError(f"Arquivo OAuth do Google não encontrado: {config.YOUTUBE_CLIENT_SECRET_FILE}")
    return Flow.from_client_secrets_file(str(config.YOUTUBE_CLIENT_SECRET_FILE), scopes=SCOPES, state=state, redirect_uri=REDIRECT)


def auth_url(state: str) -> tuple[str, str | None]:
    """Retorna (url, code_verifier). Quem chama guarda o verifier junto do state."""
    flow = _flow()
    url, _ = flow.authorization_url(access_type="offline", prompt="consent", include_granted_scopes="true", state=state)
    return url, getattr(flow, "code_verifier", None)


def handle_callback(full_url: str, state: str, code_verifier: str | None, owner: str) -> str:
    """Troca o code por tokens, salva para `owner` e retorna o nome do canal."""
    flow = _flow(state)
    if code_verifier:
        flow.code_verifier = code_verifier
    if config.PUBLIC_BASE_URL.startswith("http://"):
        os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")  # apenas para uso local
    flow.fetch_token(authorization_response=full_url)
    creds = flow.credentials
    accounts.save("youtube", owner, json.loads(creds.to_json()))
    yt = build("youtube", "v3", credentials=creds, cache_discovery=False)
    items = yt.channels().list(part="snippet", mine=True).execute().get("items", [])
    return items[0]["snippet"]["title"] if items else "YouTube"


def is_connected(owner: str = "default") -> bool:
    return accounts.load("youtube", owner) is not None


def _creds(owner: str) -> Credentials:
    data = accounts.load("youtube", owner)
    if not data:
        raise RuntimeError("YouTube não conectado.")
    creds = Credentials.from_authorized_user_info(data, SCOPES)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
        accounts.save("youtube", owner, json.loads(creds.to_json()))
    return creds


def upload(video_path: str, title: str, description: str, tags: list[str], privacy: str | None = None, owner: str = "default") -> dict:
    yt = build("youtube", "v3", credentials=_creds(owner), cache_discovery=False)
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
