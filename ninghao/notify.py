"""行动层（可选）：把高影响情报推送到飞书或企业微信群机器人。

设置环境变量 NOTIFY_WEBHOOK_URL 即启用；不设置就只更新网站。
"""

from __future__ import annotations

import logging
import os

import requests

log = logging.getLogger(__name__)
MIN_IMPACT = int(os.environ.get("NOTIFY_MIN_IMPACT", "4"))


def _text(e: dict) -> str:
    return (f"【宁好 · {e['signal']} · 影响 {e['impact']}/5】{e['headline']}\n"
            f"{e['why']}\n建议：{e['action']}\n来源：{e['source']} {e['url']}")


def push(entries: list[dict]) -> None:
    url = os.environ.get("NOTIFY_WEBHOOK_URL")
    if not url:
        return
    for e in entries:
        if e["impact"] < MIN_IMPACT:
            continue
        if "qyapi.weixin.qq.com" in url:
            payload = {"msgtype": "text", "text": {"content": _text(e)}}
        else:  # 飞书自定义机器人
            payload = {"msg_type": "text", "content": {"text": _text(e)}}
        try:
            requests.post(url, json=payload, timeout=10).raise_for_status()
        except requests.RequestException as exc:
            log.warning("推送失败：%s", exc)
