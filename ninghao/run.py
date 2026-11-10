"""宁好主流程：感知 → 补全 → 判断 → 记忆 → 行动。

用法：
    python -m ninghao.run              # 正常运行（默认用 Gemini，需要 GEMINI_API_KEY）
    python -m ninghao.run --max 5      # 只分析 5 条，试跑提示词
    python -m ninghao.run --dry-run    # 只抓取和补全，不调用模型，不写文件

切换模型：NINGHAO_PROVIDER=claude（需要 ANTHROPIC_API_KEY）。
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import yaml

from . import analyze, enrich, fetch, notify, store

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    ap = argparse.ArgumentParser(description="宁好：宁德时代海外业务实时情报")
    ap.add_argument("--max", type=int, help="本次最多分析几条新内容")
    ap.add_argument("--dry-run", action="store_true", help="只抓取，不调用模型，不写文件")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    for noisy in ("httpx", "httpx2", "trafilatura", "anthropic", "google_genai", "urllib3"):
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
    # Google 新闻链接还原成原文链接后，可能是已经处理过的新闻
    dupes = [it for it in candidates if it["id"] in seen]
    candidates = [it for it in candidates if it["id"] not in seen]
    if dupes:
        log.info("其中 %d 条还原链接后是已处理的新闻，跳过；剩 %d 条待分析", len(dupes), len(candidates))

    if args.dry_run:
        for it in candidates:
            log.info("[%s] %s | 图:%s | 正文:%d字", it["source_name"], it["title_original"][:60],
                     "有" if it.get("image") else "无", len(it.get("text", "")))
        return

    # 3. 判断：大模型以宁德时代视角写情报卡
    if not analyze.has_api_key():
        key_name = analyze.KEY_ENVS.get(analyze.PROVIDER, ("API key",))[0]
        log.warning("没有设置 %s，跳过分析（网站保持现有内容）", key_name)
        return
    log.info("用 %s / %s 分析", analyze.PROVIDER, analyze.MODEL)
    results = analyze.analyze(candidates)

    # 4. 记忆：记录已处理、更新 feed
    def ids(it: dict) -> list[str]:  # Google 新闻有两个 ID：还原前和还原后，都要记住
        return [it["id"]] + ([it["fetch_id"]] if it.get("fetch_id") else [])

    new_seen = [i for it in dupes for i in ids(it)]
    new_entries, processed = [], 0
    for item, card in results:
        if card is None:  # 失败的下次重试，不记入 seen
            continue
        processed += 1
        new_seen += ids(item)
        if card["relevant"]:
            new_entries.append(store.build_entry(item, card))
    if new_seen:
        store.save_seen(list(seen) + new_seen)
    if not new_entries:
        log.warning("分析 %d 条，没有新的相关情报，网站不更新", processed)
        return
    feed = store.merge_and_save(new_entries, settings["keep_items"])
    log.info("分析 %d 条，相关 %d 条，网站现有 %d 条", processed, len(new_entries), len(feed["items"]))

    # 5. 行动：高影响情报推送
    notify.push(new_entries)


if __name__ == "__main__":
    main()
