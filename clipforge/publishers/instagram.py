"""Publicação de Reels via Instagram Graph API (upload resumable, sem URL pública).

Requisitos: conta Instagram Business/Creator ligada a uma Página do Facebook,
app na Meta com permissões `instagram_basic` e `instagram_content_publish`,
IG_USER_ID e um token de longa duração (IG_ACCESS_TOKEN).
"""
from __future__ import annotations

import os
import time

import requests

from .. import config


def is_connected() -> bool:
    return bool(config.IG_USER_ID and config.IG_ACCESS_TOKEN)


def _graph(path: str) -> str:
    return f"https://graph.facebook.com/{config.IG_GRAPH_VERSION}/{path}"


def _json(r: requests.Response) -> dict:
    data = r.json()
    if r.status_code >= 400 or "error" in data:
        raise RuntimeError(f"Instagram API: {data.get('error', data)}")
    return data


def upload(video_path: str, caption: str, share_to_feed: bool = True) -> dict:
    if not is_connected():
        raise RuntimeError("Defina IG_USER_ID e IG_ACCESS_TOKEN no .env")
    token = config.IG_ACCESS_TOKEN

    container = _json(requests.post(
        _graph(f"{config.IG_USER_ID}/media"),
        data={
            "media_type": "REELS",
            "upload_type": "resumable",
            "caption": caption[:2200],
            "share_to_feed": "true" if share_to_feed else "false",
            "access_token": token,
        },
        timeout=60,
    ))
    cid = container["id"]
    upload_uri = container.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{config.IG_GRAPH_VERSION}/{cid}"

    size = os.path.getsize(video_path)
    with open(video_path, "rb") as fh:
        r = requests.post(
            upload_uri,
            data=fh,
            headers={"Authorization": f"OAuth {token}", "offset": "0", "file_size": str(size)},
            timeout=600,
        )
    _json(r)

    status = ""
    for _ in range(90):
        st = _json(requests.get(_graph(cid), params={"fields": "status_code,status", "access_token": token}, timeout=30))
        status = st.get("status_code", "")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram não processou o vídeo: {st.get('status')}")
        time.sleep(5)
    if status != "FINISHED":
        raise RuntimeError("Tempo esgotado aguardando o Instagram processar o Reel")

    pub = _json(requests.post(_graph(f"{config.IG_USER_ID}/media_publish"), data={"creation_id": cid, "access_token": token}, timeout=60))
    media_id = pub["id"]
    link = _json(requests.get(_graph(media_id), params={"fields": "permalink", "access_token": token}, timeout=30)).get("permalink")
    return {"id": media_id, "url": link}
