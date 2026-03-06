#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP 调试日志工具（结构化输出）

当根 logger 开启 DEBUG 时：
- 输出每次请求/响应的 URL、headers、params、body、status_code、response headers、response json/text
- 默认对 cookie/token/password/member 等敏感字段做脱敏
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

_SENSITIVE_KEYWORDS = (
    "password",
    "cookie",
    "token",
    "member",
    # 登录/兑换常用字段，避免在 DEBUG 时把可复用 code 打到日志里
    "code",
    "authorization",
    "btoken",
    "mtoken",
    "stoken",
    "x-auth-token",
    "yi-token",
)


def _is_sensitive_key(key: str) -> bool:
    k = str(key or "").lower()
    return any(word in k for word in _SENSITIVE_KEYWORDS)


def _mask_string(value: Any, *, keep_head: int = 4, keep_tail: int = 4) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool)):
        return value
    s = str(value)
    if not s:
        return s
    if len(s) <= keep_head + keep_tail:
        return "*" * len(s)
    return f"{s[:keep_head]}...{s[-keep_tail:]}(len={len(s)})"


def redact(obj: Any) -> Any:
    """
    递归脱敏：对 dict/list 结构中可能包含的 token/cookie/password/member 等字段做脱敏。
    """
    if isinstance(obj, dict):
        out: Dict[str, Any] = {}
        for k, v in obj.items():
            if _is_sensitive_key(k):
                out[str(k)] = _mask_string(v)
            else:
                out[str(k)] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    if isinstance(obj, str):
        # 对明显的长字符串做轻度脱敏（避免把 RSA 密文/长 token 打满屏）
        if len(obj) >= 120:
            return _mask_string(obj)
        return obj
    return obj


def _try_parse_json(text: str) -> Optional[Any]:
    if not text:
        return None
    t = text.lstrip()
    if not (t.startswith("{") or t.startswith("[")):
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def log_http_exchange(
    *,
    account_name: str,
    method: str,
    url: str,
    headers: Dict[str, Any],
    params: Optional[Dict[str, Any]] = None,
    data: Any = None,
    json_body: Any = None,
    timeout: Any = None,
    response: requests.Response,
    elapsed_s: float,
) -> None:
    """
    以结构化 JSON 输出请求/响应信息（DEBUG 级别）。
    """
    if not logger.isEnabledFor(logging.DEBUG):
        return

    req_payload: Dict[str, Any] = {
        "method": method,
        "url": url,
        "headers": redact(headers or {}),
        "params": redact(params or {}),
        "timeout": timeout,
    }
    if data is not None:
        req_payload["data"] = redact(data)
    if json_body is not None:
        req_payload["json"] = redact(json_body)

    resp_headers = dict(response.headers or {})
    try:
        resp_text = response.text or ""
    except Exception:
        resp_text = ""

    resp_json = _try_parse_json(resp_text)
    resp_payload: Dict[str, Any] = {
        "status_code": response.status_code,
        "elapsed_s": round(elapsed_s, 3),
        "headers": redact(resp_headers),
    }
    if resp_json is not None:
        resp_payload["json"] = redact(resp_json)
    else:
        resp_payload["text"] = (resp_text[:1500] + "...(truncated)") if len(resp_text) > 1500 else resp_text

    block = {"request": req_payload, "response": resp_payload}
    prefix = f"[{account_name}] " if account_name else ""
    logger.debug("%sHTTP 调试信息:\n%s", prefix, json.dumps(block, ensure_ascii=False, indent=2))


def request_json(
    session: requests.Session,
    *,
    method: str,
    url: str,
    headers: Dict[str, str],
    params: Optional[Dict[str, Any]] = None,
    data: Any = None,
    json_body: Any = None,
    timeout: Any = 30,
    account_name: str = "",
) -> Dict[str, Any]:
    """
    发起 HTTP 请求并返回 JSON（自动 raise_for_status），并在 DEBUG 时打印请求/响应详细信息。
    """
    start = time.time()
    resp = session.request(method=method, url=url, headers=headers, params=params, data=data, json=json_body, timeout=timeout)
    elapsed = time.time() - start
    log_http_exchange(
        account_name=account_name,
        method=method,
        url=url,
        headers=headers,
        params=params,
        data=data,
        json_body=json_body,
        timeout=timeout,
        response=resp,
        elapsed_s=elapsed,
    )
    resp.raise_for_status()
    return resp.json()
