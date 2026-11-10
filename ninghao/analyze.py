"""判断层：让大模型以宁德时代海外业务的视角读每条新闻，输出结构化情报。

支持两家模型，用环境变量 NINGHAO_PROVIDER 切换：
- gemini（默认）：Google Gemini，有免费额度，需要 GEMINI_API_KEY
- claude：Anthropic Claude，按量付费，需要 ANTHROPIC_API_KEY
两家用同一份 lens.md、同一个 JSON 表格，只有调用方式不同。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

log = logging.getLogger(__name__)

PROVIDER = os.environ.get("NINGHAO_PROVIDER", "gemini").strip().lower() or "gemini"
DEFAULT_MODELS = {
    "gemini": "gemini-3.5-flash-lite",  # 免费额度最宽的一档。SDK 走正式版 v1 接口，不支持 -latest 别名
    "claude": "claude-opus-5-5",
}
KEY_ENVS = {
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "claude": ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"),
}
MODEL = os.environ.get("NINGHAO_MODEL") or DEFAULT_MODELS.get(PROVIDER, "")
EFFORT = os.environ.get("NINGHAO_EFFORT", "medium")  # 只对 Claude 生效：low / medium / high
LENS = (Path(__file__).resolve().parent.parent / "config" / "lens.md").read_text(encoding="utf-8")

CATEGORIES = ["项目动态", "政策法规", "财务披露", "话事人发言", "竞争格局", "市场数据"]
SIGNALS = ["机会", "风险", "中性"]

# 每条要点 = 中文要点 + 原文原句。原句由代码核对，对不上就丢掉。
FACT = {
    "type": "object",
    "properties": {"fact": {"type": "string"}, "quote": {"type": "string"}},
    "required": ["fact", "quote"],
    "additionalProperties": False,
}

# 结构化输出：模型必须按这个表格填写，代码拿到的一定是合法 JSON
SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "category": {"type": "string", "enum": CATEGORIES},
        "signal": {"type": "string", "enum": SIGNALS},
        "impact": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "headline": {"type": "string"},
        "why_it_matters": {"type": "string"},
        "key_facts": {"type": "array", "items": FACT},
        "entities": {"type": "array", "items": {"type": "string"}},
        "region": {"type": "string"},
        "action": {"type": "string"},
    },
    "required": ["relevant", "category", "signal", "impact", "headline",
                 "why_it_matters", "key_facts", "entities", "region", "action"],
    "additionalProperties": False,
}



def _without_additional_properties(node):
    if isinstance(node, dict):
        return {k: _without_additional_properties(v) for k, v in node.items() if k != "additionalProperties"}
    if isinstance(node, list):
        return [_without_additional_properties(v) for v in node]
    return node


# Gemini 的 JSON 表格支持的写法少一些：整数用范围表示，不写 additionalProperties
GEMINI_SCHEMA = _without_additional_properties(SCHEMA)
GEMINI_SCHEMA["properties"]["impact"] = {"type": "integer", "minimum": 1, "maximum": 5}

SYSTEM = f"""{LENS}

## 输出
按给定的 JSON 结构输出，所有文字字段用简体中文（公司名、项目名可保留英文原文）。
- region 写地区，格式如「美国·得克萨斯」「欧洲·德国」「全球」。
- entities 列出原文中出现的关键公司、机构、项目名，最多 6 个。
- 不相关时 relevant=false，其他字段照常填写，简短即可。"""


def has_api_key() -> bool:
    return any(os.environ.get(name) for name in KEY_ENVS.get(PROVIDER, ()))


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


_PUNCT = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-", "\u00a0": " "})
MIN_QUOTE = 8  # 原句太短（比如只有「1.5 GW」）没法证明什么


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).lower().translate(_PUNCT)).strip()


def _verified_facts(facts: list, item: dict) -> list[dict]:
    """只保留原句真的出现在原文里的要点。允许原句用「...」连接原文中的几段。"""
    source = _norm(" ".join([item.get("title_original", ""), item.get("summary_original", ""),
                             item.get("text", "")]))
    kept = []
    for f in facts:
        if not isinstance(f, dict):
            continue
        fact, quote = str(f.get("fact", "")).strip(), str(f.get("quote", "")).strip()
        parts = [p.strip(" .。,，;；:：'\"") for p in re.split(r"\.\.\.|…", _norm(quote))]
        parts = [p for p in parts if p]
        if fact and parts and all(len(p) >= MIN_QUOTE and p in source for p in parts):
            kept.append({"text": fact, "quote": quote})
        else:
            log.info("要点的原句在原文里找不到，已丢弃：%s", fact[:40])
    return kept


def _finish(text: str, model: str, item: dict) -> dict | None:
    """解析 JSON 并做最后一道检查。不合格就丢掉，下次运行重试，不替模型猜。"""
    title = item["title_original"]
    try:
        card = json.loads(text)
    except json.JSONDecodeError:
        log.warning("JSON 解析失败：%s", title[:50])
        return None
    missing = [k for k in SCHEMA["required"] if k not in card]
    if (missing or card["category"] not in CATEGORIES or card["signal"] not in SIGNALS
            or card["impact"] not in (1, 2, 3, 4, 5)):
        log.warning("情报卡不合格（%s）：%s", ",".join(missing) or "取值越界", title[:50])
        return None
    card["key_facts"] = _verified_facts(list(card["key_facts"]), item)[:3]
    card["entities"] = list(card["entities"])[:6]
    card["model"] = model
    return card


# ---------- Claude ----------

def _claude_one(client, item: dict) -> dict | None:
    import anthropic

    title = item["title_original"]
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
        log.warning("触发限流，跳过：%s", title[:50])
        return None
    except anthropic.APIStatusError as exc:
        log.warning("API 错误 %s，跳过：%s", exc.status_code, title[:50])
        return None
    except anthropic.APIConnectionError:
        log.warning("网络错误，跳过：%s", title[:50])
        return None

    if resp.stop_reason in ("refusal", "max_tokens"):
        log.warning("未完成（%s）：%s", resp.stop_reason, title[:50])
        return None
    text = next((b.text for b in resp.content if b.type == "text"), "")
    return _finish(text, resp.model, item)


def _claude_all(items: list[dict]) -> list[dict | None]:
    import anthropic

    client = anthropic.Anthropic()
    with ThreadPoolExecutor(4) as pool:
        return list(pool.map(lambda it: _claude_one(client, it), items))


# ---------- Gemini ----------

class _DailyQuotaUsed(Exception):
    """当天的免费额度用完了，剩下的条目等额度重置后再分析。"""


class _StopBatch(Exception):
    """key、模型名或请求格式有问题，换下一条也一样会失败，整批停下。"""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def _gemini_one(client, item: dict, waits=(15, 30, 60)) -> dict | None:
    from google.genai import errors, types

    title = item["title_original"]
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        response_mime_type="application/json",
        response_json_schema=GEMINI_SCHEMA,
        max_output_tokens=8192,
    )
    for attempt in range(len(waits) + 1):
        try:
            resp = client.models.generate_content(model=MODEL, contents=_user_prompt(item), config=config)
            break
        except errors.APIError as exc:
            if exc.code == 429 and "PerDay" in str(exc):
                raise _DailyQuotaUsed from exc
            if exc.code in (429, 500, 503) and attempt < len(waits):
                log.info("Gemini 繁忙（%s），%d 秒后重试：%s", exc.code, waits[attempt], title[:40])
                time.sleep(waits[attempt])
                continue
            if exc.code in (400, 401, 403, 404):
                raise _StopBatch(exc.code, exc.message or str(exc)) from exc
            log.warning("Gemini 错误 %s（%s），跳过：%s", exc.code, (exc.message or "")[:120], title[:50])
            return None
        except Exception as exc:  # 网络断开等
            log.warning("Gemini 调用失败（%s），跳过：%s", type(exc).__name__, title[:50])
            return None

    finish = resp.candidates[0].finish_reason if resp.candidates else None
    text = resp.text if resp.candidates else None
    if not text or str(finish).endswith("MAX_TOKENS"):
        log.warning("Gemini 未返回完整结果（%s）：%s", finish, title[:50])
        return None
    return _finish(text, resp.model_version or MODEL, item)


def _gemini_all(items: list[dict]) -> list[dict | None]:
    from google import genai

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    client = genai.Client(api_key=key)
    cards: list[dict | None] = []
    for i, item in enumerate(items):  # 免费额度有每分钟上限，所以一条一条来
        try:
            cards.append(_gemini_one(client, item))
        except _DailyQuotaUsed:
            log.warning("Gemini 今日免费额度已用完，剩下 %d 条等额度重置后再分析", len(items) - i)
            cards.extend([None] * (len(items) - i))
            break
        except _StopBatch as exc:
            log.error("Gemini 错误 %s，本次停止分析：%s", exc.code, str(exc)[:300])
            if exc.code == 404:
                _log_available_models(client)
            cards.extend([None] * (len(items) - i))
            break
    return cards


def _log_available_models(client) -> None:
    """模型名不可用时，列出这个 key 能调用的模型，方便改 NINGHAO_MODEL。"""
    try:
        names = [m.name.removeprefix("models/") for m in client.models.list()
                 if "generateContent" in (m.supported_actions or [])]
    except Exception as exc:
        log.error("也没能列出可用模型（%s）", type(exc).__name__)
        return
    log.error("当前模型 %s 不可用。这个 key 能用的模型：%s", MODEL, ", ".join(names) or "（空）")


def analyze(items: list[dict]) -> list[tuple[dict, dict | None]]:
    if PROVIDER == "gemini":
        cards = _gemini_all(items)
    elif PROVIDER == "claude":
        cards = _claude_all(items)
    else:
        raise SystemExit(f"不认识的 NINGHAO_PROVIDER：{PROVIDER}（可选 gemini 或 claude）")
    return list(zip(items, cards))
