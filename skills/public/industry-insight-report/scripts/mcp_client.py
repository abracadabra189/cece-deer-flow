"""最小 MCP Streamable-HTTP 客户端（FastMCP 兼容）：initialize → tools/list → tools/call。"""
from __future__ import annotations

import json
import uuid

import httpx


class MCPError(RuntimeError):
    pass


class MCPClient:
    def __init__(self, url: str, timeout: float = 120.0):
        self.url = url
        self.timeout = timeout
        self.session_id: str | None = None
        self._client = httpx.Client(timeout=timeout, headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        })

    def _post(self, payload: dict, expect_reply: bool = True):
        headers = {"mcp-session-id": self.session_id} if self.session_id else {}
        r = self._client.post(self.url, json=payload, headers=headers)
        sid = r.headers.get("mcp-session-id")
        if sid:
            self.session_id = sid
        if r.status_code >= 400:
            raise MCPError(f"HTTP {r.status_code}: {r.text[:300]}")
        if not expect_reply:
            return None
        return self._parse(r.text)

    @staticmethod
    def _parse(text: str):
        text = text.strip()
        if not text:
            return None
        if text.startswith("{"):
            data = json.loads(text)
        else:  # SSE frames
            data = None
            for line in text.splitlines():
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if chunk and chunk != "[DONE]":
                        data = json.loads(chunk)
        if data is None:
            raise MCPError("empty MCP response")
        if "error" in data:
            raise MCPError(f"MCP error {data['error'].get('code')}: {data['error'].get('message')}")
        return data.get("result")

    def initialize(self):
        self._post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "industry-insight-report", "version": "1.0"}}})
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"}, expect_reply=False)
        return self

    def tools(self):
        res = self._post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) or {}
        return res.get("tools", [])

    def call(self, name: str, arguments: dict | None = None):
        res = self._post({"jsonrpc": "2.0", "id": uuid.uuid4().int % 100000,
                          "method": "tools/call",
                          "params": {"name": name, "arguments": arguments or {}}})
        if res is None:
            raise MCPError("empty tools/call result")
        if res.get("isError"):
            content = res.get("content") or []
            msg = " ".join(c.get("text", "") for c in content if isinstance(c, dict))
            raise MCPError(msg[:400] or "tool error")
        # FastMCP: structuredContent 或 content[].text(JSON)
        if isinstance(res.get("structuredContent"), (dict, list)):
            return res["structuredContent"]
        parts = []
        for c in res.get("content") or []:
            if isinstance(c, dict) and c.get("type") == "text":
                parts.append(c.get("text", ""))
        text = "\n".join(parts).strip()
        try:
            return json.loads(text) if text else res
        except json.JSONDecodeError:
            return text

    def close(self):
        self._client.close()

    def __enter__(self):
        return self.initialize()

    def __exit__(self, *exc):
        self.close()