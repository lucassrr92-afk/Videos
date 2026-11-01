"""Publicação no TikTok via Content Posting API (Direct Post).

Requisitos: app em developers.tiktok.com com o produto "Content Posting API" e
escopo `video.publish`. Enquanto o app não for auditado pelo TikTok, os posts
só podem ser privados (SELF_ONLY).
"""
from __future__ import annotations

import os
import time
import urllib.parse

import requests

from .. import accounts, config

API = "https://open.tiktokapis.com/v2"
REDIRECT = f"{config.PUBLIC_BASE_URL}/auth/tiktok/callback"


def auth_url(state: str) -> str:
    if not config.TIKTOK_CLIENT_KEY:
        raise RuntimeError("Defina TIKTOK_CLIENT_KEY e TIKTOK_CLIENT_SECRET no .env")
    q = {
        "client_key": config.TIKTOK_CLIENT_KEY,
        "scope": "user.info.basic,video.publish",
        "response_type": "code",
        "redirect_uri": REDIRECT,
        "state": state,
    }
    return "https://www.tiktok.com/v2/auth/authorize/?" + urllib.parse.urlencode(q)


def _save(owner: str, tok: dict) -> dict:
    if "access_token" not in tok:
        raise RuntimeError(f"TikTok OAuth falhou: {tok}")
    tok["obtained_at"] = int(time.time())
    accounts.save("tiktok", owner, tok)
    return tok


def handle_callback(code: str, owner: str) -> str:
    """Troca o code por tokens (o state já foi validado por quem chama). Retorna o nome do perfil."""
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
    tok = _save(owner, r.json())
    info = requests.get(
        f"{API}/user/info/", params={"fields": "display_name"},
        headers={"Authorization": f"Bearer {tok['access_token']}"}, timeout=30,
    ).json()
    return info.get("data", {}).get("user", {}).get("display_name") or "TikTok"


def is_connected(owner: str = "default") -> bool:
    return accounts.load("tiktok", owner) is not None


def _token(owner: str) -> str:
    tok = accounts.load("tiktok", owner)
    if not tok:
        raise RuntimeError("TikTok não conectado.")
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
        tok = _save(owner, r.json())
    return tok["access_token"]


def creator_info(owner: str) -> dict:
    """Nome do perfil e opções de privacidade permitidas (exibir no modal de publicação)."""
    headers = {"Authorization": f"Bearer {_token(owner)}", "Content-Type": "application/json; charset=UTF-8"}
    return _check(requests.post(f"{API}/post/publish/creator_info/query/", headers=headers, timeout=30))


def _check(resp: requests.Response) -> dict:
    data = resp.json()
    err = data.get("error", {})
    if resp.status_code >= 400 or (err and err.get("code") not in (None, "ok")):
        raise RuntimeError(f"TikTok API: {err or data}")
    return data.get("data", {})


def upload(video_path: str, caption: str, privacy: str | None = None, owner: str = "default") -> dict:
    token = _token(owner)
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
