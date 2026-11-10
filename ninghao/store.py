"""记忆层：记住看过哪些条目（去重），维护网站读取的 feed.json。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "data" / "state.json"
FEED = ROOT / "site" / "data" / "feed.json"
MAX_SEEN = 5000


def _load(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def load_seen() -> set[str]:
    return set(_load(STATE, {"seen": []})["seen"])


def save_seen(seen_ids: list[str]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({"seen": seen_ids[-MAX_SEEN:]}, ensure_ascii=False, indent=0),
                     encoding="utf-8")


def load_feed() -> dict:
    return _load(FEED, {"updated": None, "items": []})


def build_entry(item: dict, card: dict) -> dict:
    """把原文信息和模型写的情报卡合并成网站展示用的一条。"""
    return {
        "id": item["id"],
        "url": item["url"],
        "source": item["source_name"],
        "title_original": item["title_original"],
        "published": item.get("published"),
        "broadcast": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "image": item.get("image"),
        "headline": card["headline"],
        "why": card["why_it_matters"],
        "facts": card["key_facts"],
        "entities": card["entities"],
        "region": card["region"],
        "category": card["category"],
        "signal": card["signal"],
        "impact": card["impact"],
        "action": card["action"],
        "model": card.get("model"),
    }


def merge_and_save(new_entries: list[dict], keep: int) -> dict:
    feed = load_feed()
    by_id = {e["id"]: e for e in feed["items"]}
    for e in new_entries:
        old = by_id.get(e["id"])
        if old:  # 重新分析时保留第一次播报的时间
            e["broadcast"] = old["broadcast"]
        by_id[e["id"]] = e
    items = sorted(by_id.values(), key=lambda e: e.get("published") or e["broadcast"], reverse=True)
    feed = {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "items": items[:keep]}
    FEED.parent.mkdir(parents=True, exist_ok=True)
    FEED.write_text(json.dumps(feed, ensure_ascii=False, indent=1), encoding="utf-8")
    return feed
