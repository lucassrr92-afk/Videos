"""Publicação no TikTok via Content Posting API (Direct Post).

Requisitos: app em developers.tiktok.com com o produto "Content Posting API" e
escopo `video.publish`. Enquanto o app não for auditado pelo TikTok, os posts
só podem ser privados (SELF_ONLY).
"""
from __future__ import annotations

import json
import os
import secrets
import time
import urllib.parse

import requests

from .. import config

API = "https://open.tiktokapis.com/v2"
TOKEN_FILE = config.TOKENS_DIR / "tiktok.json"
REDIRECT = f"{config.PUBLIC_BASE_URL}/auth/tiktok/callback"


def auth_url() -> str:
    if not config.TIKTOK_CLIENT_KEY:
        raise RuntimeError("Defina TIKTOK_CLIENT_KEY e TIKTOK_CLIENT_SECRET no .env")
    state = secrets.token_urlsafe(16)
    (config.TOKENS_DIR / "tiktok_state.txt").write_text(state)
    q = {
        "client_key": config.TIKTOK_CLIENT_KEY,
        "scope": "user.info.basic,video.publish",
        "response_type": "code",
        "redirect_uri": REDIRECT,
        "state": state,
    }
    return "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(q)


def _save(tok: dict) -> dict:
    if "access_token" not in tok:
        raise RuntimeError(f"TikTok OAuth falhou: {tok}")
    tok["obtained_at"] = int(time.time())
    TOKEN_FILE.write_text(json.dumps(tok))
    return tok


def handle_callback(code: str, state: str) -> None:
    expected = (config.TOKENS_DIR / "tiktok_state.txt").read_text()
    if state != expected:
        raise RuntimeError("state inválido no callback do TikTok")
    r = requests.post(
        f"{API}/oauth/token/",
        data={
            "client_key": config.TIKTOK_CLIENT_KEY,
            "client_secret": config.TIKTOK_CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT,
        },
        timeout=30,
    )
    _save(r.json())


def is_connected() -> bool:
    return TOKEN_FILE.exists()


def _token() -> str:
    if not TOKEN_FILE.exists():
        raise RuntimeError("TikTok não conectado. Abra /auth/tiktok para autorizar.")
    tok = json.loads(TOKEN_FILE.read_text())
    if time.time() > tok["obtained_at"] + tok.get("expires_in", 86400) - 300:
        r = requests.post(
            f"{API}/oauth/token/",
            data={
                "client_key": config.TIKTOK_CLIENT_KEY,
                "client_secret": config.TIKTOK_CLIENT_SECRET,
                "grant_type": "refresh_token",
                "refresh_token": tok["refresh_token"],
            },
            timeout=30,
        )
        tok = _save(r.json())
    return tok["access_token"]


def _check(resp: requests.Response) -> dict:
    data = resp.json()
    err = data.get("error", {})
    if resp.status_code >= 400 or (err and err.get("code") not in (None, "ok")):
        raise RuntimeError(f"TikTok API: {err or data}")
    return data.get("data", {})


def upload(video_path: str, caption: str, privacy: str | None = None) -> dict:
    token = _token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8"}

    creator = _check(requests.post(f"{API}/post/publish/creator_info/query/", headers=headers, timeout=30))
    allowed = creator.get("privacy_level_options", [])
    level = privacy or config.TIKTOK_PRIVACY
    if allowed and level not in allowed:
        level = "SELF_ONLY" if "SELF_ONLY" in allowed else allowed[0]

    size = os.path.getsize(video_path)
    chunk = size if size <= 64 * 1024 * 1024 else 10 * 1024 * 1024
    total_chunks = 1 if chunk == size else size // chunk  # o último chunk absorve o resto
    init = _check(requests.post(
        f"{API}/post/publish/video/init/",
        headers=headers,
        json={
            "post_info": {
                "title": caption[:2200],
                "privacy_level": level,
                "disable_duet": False,
                "disable_comment": False,
                "disable_stitch": False,
                "video_cover_timestamp_ms": 1000,
            },
            "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": total_chunks},
        },
        timeout=60,
    ))
    publish_id, upload_url = init["publish_id"], init["upload_url"]

    with open(video_path, "rb") as fh:
        for i in range(total_chunks):
            start = i * chunk
            end = size - 1 if i == total_chunks - 1 else start + chunk - 1
            fh.seek(start)
            data = fh.read(end - start + 1)
            r = requests.put(
                upload_url,
                data=data,
                headers={"Content-Type": "video/mp4", "Content-Length": str(len(data)), "Content-Range": f"bytes {start}-{end}/{size}"},
                timeout=300,
            )
            if r.status_code not in (200, 201, 206):
                raise RuntimeError(f"TikTok upload chunk {i}: HTTP {r.status_code} {r.text[:300]}")

    status = {}
    for _ in range(60):
        status = _check(requests.post(f"{API}/post/publish/status/fetch/", headers=headers, json={"publish_id": publish_id}, timeout=30))
        if status.get("status") in ("PUBLISH_COMPLETE", "FAILED"):
            break
        time.sleep(5)
    if status.get("status") == "FAILED":
        raise RuntimeError(f"TikTok recusou o vídeo: {status.get('fail_reason')}")
    ids = status.get("publicaly_available_post_id") or status.get("publicly_available_post_id") or []
    return {"publish_id": publish_id, "status": status.get("status"), "privacy": level, "post_ids": ids}
