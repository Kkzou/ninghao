"""补全原文：还原 Google 新闻链接，抓取正文和配图（og:image）。"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

import requests
import trafilatura

from .fetch import UA, make_id

log = logging.getLogger(__name__)
MAX_TEXT = 6000  # 交给模型的正文上限（字符）


def _decode_google(url: str) -> str | None:
    try:
        from googlenewsdecoder import gnewsdecoder
        r = gnewsdecoder(url, interval=0.5)
        return r.get("decoded_url") if r else None
    except Exception as exc:
        log.debug("Google 链接还原失败: %s", exc)
        return None


def enrich_one(item: dict) -> dict:
    if item.pop("needs_decode", False):
        real = _decode_google(item["url"])
        if real:
            item["fetch_id"] = item["id"]  # 记下 Google 链接的 ID，下次抓到同一条就能直接跳过
            item["url"] = real
            item["id"] = make_id(real)
    try:
        resp = requests.get(item["url"], headers={"User-Agent": UA}, timeout=12)
        if resp.encoding is None or resp.encoding.lower() == "iso-8859-1":
            resp.encoding = resp.apparent_encoding  # 中文网站常不声明编码，避免乱码
        html = resp.text if resp.ok else None
    except requests.RequestException:
        html = None
    item["text"] = ""
    if html:
        text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
        item["text"] = text[:MAX_TEXT]
        meta = trafilatura.extract_metadata(html)
        if meta and meta.image and not item.get("image"):
            item["image"] = meta.image
    return item


def enrich(items: list[dict], workers: int = 8) -> list[dict]:
    with ThreadPoolExecutor(workers) as pool:
        return list(pool.map(enrich_one, items))
