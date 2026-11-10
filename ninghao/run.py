"""宁好主流程：感知 → 补全 → 判断 → 记忆 → 行动。

用法：
    python -m ninghao.run              # 正常运行（需要 ANTHROPIC_API_KEY）
    python -m ninghao.run --max 5      # 只分析 5 条，试跑提示词
    python -m ninghao.run --dry-run    # 只抓取和补全，不调用 Claude，不写文件
"""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

import yaml

from . import analyze, enrich, fetch, notify, store

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser(description="宁好：宁德时代海外业务实时情报")
    ap.add_argument("--max", type=int, help="本次最多分析几条新内容")
    ap.add_argument("--dry-run", action="store_true", help="只抓取，不调用 Claude，不写文件")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpx2", "trafilatura", "anthropic", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.ERROR)
    log = logging.getLogger("ninghao")

    config = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    settings = config["settings"]
    limit = args.max or settings["max_new_per_run"]

    # 1. 感知：抓取并粗筛
    seen = store.load_seen()
    candidates = [it for it in fetch.collect(config) if it["id"] not in seen]
    log.info("新候选 %d 条，本次处理前 %d 条", len(candidates), min(limit, len(candidates)))
    candidates = candidates[:limit]

    # 2. 补全：原文链接、正文、配图
    candidates = enrich.enrich(candidates)
    candidates = [it for it in candidates if it["id"] not in seen]  # Google 链接还原后再去重一次

    if args.dry_run:
        for it in candidates:
            log.info("[%s] %s | 图:%s | 正文:%d字", it["source_name"], it["title_original"][:60],
                     "有" if it.get("image") else "无", len(it.get("text", "")))
        return

    # 3. 判断：Claude 以宁德时代视角写情报卡
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        log.warning("没有设置 ANTHROPIC_API_KEY，跳过分析（网站保持现有内容）")
        return
    results = analyze.analyze(candidates)

    # 4. 记忆：记录已处理、更新 feed
    new_entries, processed = [], []
    for item, card in results:
        if card is None:  # 失败的下次重试，不记入 seen
            continue
        processed.append(item["id"])
        if card["relevant"]:
            new_entries.append(store.build_entry(item, card))
    store.save_seen(list(seen) + processed)
    feed = store.merge_and_save(new_entries, settings["keep_items"])
    log.info("分析 %d 条，相关 %d 条，网站现有 %d 条", len(processed), len(new_entries), len(feed["items"]))

    # 5. 行动：高影响情报推送
    notify.push(new_entries)


if __name__ == "__main__":
    main()
