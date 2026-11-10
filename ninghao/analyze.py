"""判断层：让 Claude 以宁德时代海外业务的视角读每条新闻，输出结构化情报。"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic

log = logging.getLogger(__name__)

MODEL = os.environ.get("NINGHAO_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("NINGHAO_EFFORT", "medium")  # low / medium / high
LENS = (Path(__file__).resolve().parent.parent / "config" / "lens.md").read_text(encoding="utf-8")

CATEGORIES = ["项目动态", "政策法规", "财务披露", "话事人发言", "竞争格局", "市场数据"]

# 结构化输出：Claude 必须按这个表格填写，代码拿到的一定是合法 JSON
SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "category": {"type": "string", "enum": CATEGORIES},
        "signal": {"type": "string", "enum": ["机会", "风险", "中性"]},
        "impact": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "headline": {"type": "string"},
        "why_it_matters": {"type": "string"},
        "key_facts": {"type": "array", "items": {"type": "string"}},
        "entities": {"type": "array", "items": {"type": "string"}},
        "region": {"type": "string"},
        "action": {"type": "string"},
    },
    "required": ["relevant", "category", "signal", "impact", "headline",
                 "why_it_matters", "key_facts", "entities", "region", "action"],
    "additionalProperties": False,
}

SYSTEM = f"""{LENS}

## 输出
按给定的 JSON 结构输出，所有文字字段用简体中文（公司名、项目名可保留英文原文）。
- region 写地区，格式如「美国·得克萨斯」「欧洲·德国」「全球」。
- entities 列出原文中出现的关键公司、机构、项目名，最多 6 个。
- 不相关时 relevant=false，其他字段照常填写，简短即可。"""


def _user_prompt(item: dict) -> str:
    body = item.get("text") or item.get("summary_original") or "（未能获取正文，仅有标题）"
    return (
        f"来源：{item['source_name']}\n"
        f"发布时间：{item.get('published') or '未知'}\n"
        f"原标题：{item['title_original']}\n"
        f"链接：{item['url']}\n\n"
        f"<article>\n{body}\n</article>\n\n"
        "请以宁德时代海外业务情报分析师的身份，判断这条信息并填写情报卡。"
    )


def analyze_one(client: anthropic.Anthropic, item: dict) -> dict | None:
    try:
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",  # 被安全策略拒绝时，服务端自动换模型重试
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": _user_prompt(item)}],
        )
    except anthropic.RateLimitError:
        log.warning("触发限流，跳过：%s", item["title_original"][:50])
        return None
    except anthropic.APIStatusError as exc:
        log.warning("API 错误 %s，跳过：%s", exc.status_code, item["title_original"][:50])
        return None
    except anthropic.APIConnectionError:
        log.warning("网络错误，跳过：%s", item["title_original"][:50])
        return None

    if resp.stop_reason in ("refusal", "max_tokens"):
        log.warning("未完成（%s）：%s", resp.stop_reason, item["title_original"][:50])
        return None
    text = next((b.text for b in resp.content if b.type == "text"), "")
    try:
        card = json.loads(text)
    except json.JSONDecodeError:
        log.warning("JSON 解析失败：%s", item["title_original"][:50])
        return None
    card["key_facts"] = card["key_facts"][:3]
    card["entities"] = card["entities"][:6]
    card["model"] = resp.model
    return card


def analyze(items: list[dict], workers: int = 4) -> list[tuple[dict, dict | None]]:
    client = anthropic.Anthropic()
    with ThreadPoolExecutor(workers) as pool:
        cards = list(pool.map(lambda it: analyze_one(client, it), items))
    return list(zip(items, cards))
