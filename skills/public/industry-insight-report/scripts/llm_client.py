"""批量/交互模式可选的 LLM 直连客户端（OpenAI 兼容）。凭据仅来自 operator env。"""
from __future__ import annotations

import json
import os
import urllib.request


def configured() -> bool:
    return bool(os.environ.get("REPORT_LLM_BASE_URL") and os.environ.get("REPORT_LLM_API_KEY"))


def complete(system: str, prompt: str, max_tokens: int = 4096) -> str:
    if not configured():
        raise RuntimeError("REPORT_LLM_* not configured")
    url = os.environ["REPORT_LLM_BASE_URL"].rstrip("/") + "/chat/completions"
    body = {
        "model": os.environ.get("REPORT_LLM_MODEL", "gpt-4o-mini"),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ['REPORT_LLM_API_KEY']}"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]
