"""感知层：从各信息源抓取最新条目，统一成同一种格式。"""

from __future__ import annotations

import hashlib
import logging
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests

log = logging.getLogger(__name__)

UA = "Mozilla/5.0 (compatible; NingHaoBot/0.1; +https://github.com/)"
TIMEOUT = 15


def make_id(url: str) -> str:
    """用规范化后的链接生成稳定 ID，用于去重。"""
    parts = urllib.parse.urlsplit(url.strip())
    query = urllib.parse.urlencode(
        [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if not k.lower().startswith("utm_")]
    )
    norm = urllib.parse.urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))
    return hashlib.sha1(norm.encode()).hexdigest()[:16]


def _parse_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            return datetime(*t[:6], tzinfo=timezone.utc)
    for key in ("published", "updated"):
        if entry.get(key):
            try:
                return parsedate_to_datetime(entry[key]).astimezone(timezone.utc)
            except (TypeError, ValueError):
                pass
    return None


def _rss_image(entry) -> str | None:
    if entry.get("media_content"):
        return entry.media_content[0].get("url")
    if entry.get("media_thumbnail"):
        return entry.media_thumbnail[0].get("url")
    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("image"):
            return enc.get("href")
    html = entry.get("summary", "") + "".join(c.get("value", "") for c in entry.get("content", []))
    m = re.search(r'<img[^>]+src="([^"]+)"', html)
    return m.group(1) if m else None


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text or "")).strip()


def _item(src: dict, url: str, title: str, published: datetime | None, summary: str = "",
          image: str | None = None, source_name: str | None = None) -> dict:
    return {
        "id": make_id(url),
        "url": url,
        "source_id": src["id"],
        "source_name": source_name or src["name"],
        "title_original": _strip_html(title),
        "summary_original": _strip_html(summary)[:1200],
        "published": published.isoformat() if published else None,
        "image": image,
    }


def fetch_rss(src: dict) -> list[dict]:
    feed = feedparser.parse(src["url"], agent=UA)
    items = []
    for e in feed.entries[: src.get("max_items", 20)]:
        if not e.get("link"):
            continue
        items.append(_item(src, e.link, e.get("title", ""), _parse_time(e),
                           e.get("summary", ""), _rss_image(e)))
    return items


def fetch_google_news(src: dict) -> list[dict]:
    """Google 新闻搜索 RSS。链接是 Google 的跳转地址，在 enrich 阶段再还原成原文链接。"""
    if src.get("lang") == "zh":
        params = {"hl": "zh-CN", "gl": "CN", "ceid": "CN:zh-Hans"}
    else:
        params = {"hl": "en-US", "gl": "US", "ceid": "US:en"}
    params["q"] = f'{src["query"]} when:3d'
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)
    feed = feedparser.parse(url, agent=UA)
    items = []
    for e in feed.entries[: src.get("max_items", 10)]:
        title = e.get("title", "")
        publisher = e.get("source", {}).get("title")
        # Google 新闻标题末尾带「 - 媒体名」，去掉
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3]
        item = _item(src, e.link, title, _parse_time(e), "", None,
                     source_name=publisher or src["name"])
        item["needs_decode"] = True
        items.append(item)
    return items


def fetch_federal_register(src: dict) -> list[dict]:
    items = []
    for term in src.get("terms", []):
        params = [
            ("per_page", "10"), ("order", "newest"), ("conditions[term]", term),
            ("conditions[type][]", "RULE"), ("conditions[type][]", "PRORULE"),
            ("conditions[type][]", "PRESDOCU"), ("conditions[type][]", "NOTICE"),
        ]
        for f in ("title", "abstract", "html_url", "publication_date", "type", "agencies"):
            params.append(("fields[]", f))
        try:
            r = requests.get("https://www.federalregister.gov/api/v1/documents.json",
                             params=params, headers={"User-Agent": UA}, timeout=TIMEOUT)
            r.raise_for_status()
        except requests.RequestException as exc:
            log.warning("联邦公报查询失败 %s: %s", term, exc)
            continue
        for d in r.json().get("results", []):
            if re.search(r"Combined Notice of Filings|Sunshine Act|Agency Information Collection",
                         d.get("title", ""), re.I):
                continue
            agency = d["agencies"][0]["name"] if d.get("agencies") else "联邦公报"
            pub = datetime.fromisoformat(d["publication_date"]).replace(tzinfo=timezone.utc)
            items.append(_item(src, d["html_url"], d["title"], pub, d.get("abstract") or "",
                               None, source_name=f"联邦公报 · {agency}"))
    return items


FETCHERS = {"rss": fetch_rss, "google_news": fetch_google_news, "federal_register": fetch_federal_register}


def passes_prefilter(item: dict, keywords: list[str]) -> bool:
    text = f" {item['title_original']} {item['summary_original']} ".lower()
    return any(k.lower() in text for k in keywords)


def collect(config: dict) -> list[dict]:
    """抓取所有信息源，按时间窗口和关键词粗筛，按标题去重。"""
    settings = config["settings"]
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings["lookback_hours"])
    keywords = config.get("prefilter_keywords", [])
    out, seen_titles = [], set()
    for src in config["sources"]:
        try:
            items = FETCHERS[src["type"]](src)
        except Exception as exc:  # 单个源出错不影响其他源
            log.warning("信息源 %s 抓取失败: %s", src["id"], exc)
            continue
        kept = 0
        for it in items:
            if it["published"] and datetime.fromisoformat(it["published"]) < cutoff:
                continue
            if re.match(r"(sponsored|advertorial|webinar)\b", it["title_original"], re.I):
                continue
            if src.get("prefilter") and not passes_prefilter(it, keywords):
                continue
            key = re.sub(r"\W+", "", it["title_original"].lower())[:60]
            if key in seen_titles:
                continue
            seen_titles.add(key)
            out.append(it)
            kept += 1
        log.info("%-22s 抓到 %3d 条，保留 %3d 条", src["id"], len(items), kept)
    out.sort(key=lambda x: x["published"] or "", reverse=True)
    return out
