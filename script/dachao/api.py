#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
大潮（新流程）API 模块

特点：
- 账号密码登录（passport -> vapp -> aihoge member）
- 动态获取签到/阅读活动 tid
- RSA 加密 params（PKCS#1 v1.5 + Base64）

注意：
- 部分接口涉及 X-SIGNATURE / signature 字段，线上可能有更严格的校验；本实现提供可覆盖的“签名生成”入口。
- 请勿在日志中打印 token/cookie 等敏感信息。
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, quote, urlparse

import requests
from http_debug import request_json

try:
    # dachao 内置的滑块验证码计算
    from captcha import calculate_slide_offset  # type: ignore
except Exception:  # pragma: no cover
    calculate_slide_offset = None

try:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding
except ImportError:  # pragma: no cover
    serialization = None
    padding = None

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = (10, 30)

REDEEM_ALREADY_RECEIVED_CODES = {"is_receive_packet"}


def interpret_redeem_response(resp: Dict[str, Any]) -> Dict[str, Any]:
    """
    统一解析红包兑换返回。

    Returns:
        {
          "ok": bool,              # 是否视为成功
          "already_received": bool,# 是否为“已领取”
          "code": str,             # 业务码（字符串化）
          "message": str,          # 业务信息
        }
    """
    if not isinstance(resp, dict):
        return {"ok": False, "already_received": False, "code": "", "message": "invalid_response"}

    success = resp.get("success")
    if success in (True, 1, "1"):
        return {"ok": True, "already_received": False, "code": "success", "message": ""}

    if resp.get("code") == 0:
        return {"ok": True, "already_received": False, "code": "code=0", "message": str(resp.get("message") or "")}

    error_code = resp.get("error_code")
    error_code_str = str(error_code) if error_code is not None else ""
    error_message = str(resp.get("error_message") or resp.get("message") or resp.get("error") or "")

    if error_code_str in REDEEM_ALREADY_RECEIVED_CODES:
        return {"ok": True, "already_received": True, "code": error_code_str, "message": error_message or "已领取"}

    # 部分接口可能用 error_code=0 表示成功
    if error_code == 0 or error_code_str == "0":
        return {"ok": True, "already_received": False, "code": error_code_str, "message": error_message}

    return {"ok": False, "already_received": False, "code": error_code_str, "message": error_message or "未知错误"}


PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0G25Cq2HxQQ+gX9H2dzb
6sbRtHzD8JbHRmOrAFzaWI2kdzbPuga4ZlqxOAyoAm8ucIAeKD4joUn+dN1wYC03
qCgloNU21KUJUls/Htp2RwxpmoncSIAOZvSQQ6Kl3vLPYlG6GetwYYN83sG85K+3
w4D89hBGHuYqKQyQsUvntxi5UVoNfo674QsCvqxHxZAuEXKoEagzUoSu8gWrDTuh
RK4aQcDpnCslwKycaO63UBvfTlBG0Jc7sqzXxapTArbqaA58XCM8dRIZdp7DR/V7
qucn/PwIOGJrOu09/cjndwIpeki8HXa9rvgWwiwZCy289vgRoxzIcLrQJ2oC1MK2
RwIDAQAB
-----END PUBLIC KEY-----"""

# vapp X-SIGNATURE 盐值（与 script/dachao_bak/api.py 一致）
VAPP_SIGNATURE_SALT = "FR*r!isE5W"


def _mask_mobile(mobile: str) -> str:
    m = str(mobile or "")
    if len(m) < 7:
        return "*" * len(m)
    return f"{m[:3]}****{m[-4:]}"


def _mask_secret(value: str, keep_head: int = 4, keep_tail: int = 4) -> str:
    s = str(value or "")
    if not s:
        return ""
    if len(s) <= keep_head + keep_tail:
        return "*" * len(s)
    return f"{s[:keep_head]}...{s[-keep_tail:]}(len={len(s)})"


def _safe_json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _parse_tid_from_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    tid = (qs.get("tid") or [""])[0]
    return str(tid or "")


@dataclass
class NewDachaoAccountConfig:
    account_name: str
    phone_number: str
    password_encrypted: str
    tenant_id: str = "94"
    client_id: str = "10048"
    # 用于 vapp 登录阶段请求头的 X-SESSION-ID（抓包里的 24 位左右 hex 字符串）
    # 注意：这不是 vapp 登录成功后返回的 session.id
    session_id: str = ""
    # vapp 与 aihoge 使用同一个 UA（统一从配置读取，不提供默认值）
    user_agent: str = ""

    # 可选：如果你抓包有 cookie，可填（不要写进 git）
    passport_cookies: str = ""
    vapp_cookies: str = ""
    aihoge_cookies: str = ""

    # 可选：用于论坛/活动（与 script/dachao_bak 兼容字段）
    forum_session_id: str = ""
    forum_cookies: str = ""
    forum_tenant_id: str = "10"

    # 可选：红包兑换用 member（抽到现金红包 type=3 时，用此 member 去兑换 code）
    # 兼容历史字段：withdraw_member
    redeem_member: str = ""
    # 可选：红包兑换时使用的 Cookie（抓包为 HYPERF_SESSION_ID=...），不填则复用 aihoge_cookies
    redeem_cookies: str = ""
    # 可选：红包兑换时使用的 UA（不填则复用 user_agent）
    redeem_user_agent: str = ""

    # 可选：如果服务端对签名有校验，可在这里覆盖/补充
    passport_signature_salt: str = ""
    aihoge_signature_salt: str = ""
    sign_lottery_id: str = ""  # 若无法自动发现，可手动填写

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NewDachaoAccountConfig":
        account_name = (data.get("account_name") or "未命名账号").strip()
        phone_number = str(data.get("phone_number") or "").strip()
        password_encrypted = str(data.get("password_encrypted") or data.get("password") or "").strip()
        user_agent = str(
            data.get("user_agent")
            or data.get("user_agent_vapp")
            or data.get("user_agent_aihoge")
            or ""
        ).strip()

        if not phone_number:
            raise ValueError(f"账号【{account_name}】缺少必填字段: phone_number")
        if not password_encrypted:
            raise ValueError(f"账号【{account_name}】缺少必填字段: password_encrypted")
        if not user_agent:
            raise ValueError(f"账号【{account_name}】缺少必填字段: user_agent")

        return cls(
            account_name=account_name,
            phone_number=phone_number,
            password_encrypted=password_encrypted,
            tenant_id=str(data.get("tenant_id") or "94"),
            client_id=str(data.get("client_id") or "10048"),
            session_id=str(data.get("session_id") or ""),
            user_agent=user_agent,
            passport_cookies=str(data.get("passport_cookies") or ""),
            vapp_cookies=str(data.get("vapp_cookies") or ""),
            aihoge_cookies=str(data.get("cookies") or data.get("aihoge_cookies") or ""),
            forum_session_id=str(data.get("forum_session_id") or ""),
            forum_cookies=str(data.get("forum_cookies") or ""),
            forum_tenant_id=str(data.get("forum_tenant_id") or "10"),
            redeem_member=str(data.get("redeem_member") or data.get("withdraw_member") or ""),
            redeem_cookies=str(data.get("redeem_cookies") or ""),
            redeem_user_agent=str(data.get("redeem_user_agent") or ""),
            passport_signature_salt=str(data.get("passport_signature_salt") or ""),
            aihoge_signature_salt=str(data.get("aihoge_signature_salt") or ""),
            sign_lottery_id=str(data.get("sign_lottery_id") or ""),
        )


@dataclass
class DachaoLoginContext:
    session_id: str
    account_id: str
    tenant_id: str
    nick_name: str
    avatar_url: str
    mobile: str


class RsaEncryptor:
    def __init__(self) -> None:
        # aihoge 侧 params 字段使用 RSA 公钥加密（PKCS#1 v1.5），再 Base64 传输
        if serialization is not None:
            self._pubkey = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode("utf-8"))
        else:
            self._pubkey = None

    def encrypt_base64_pkcs1v15(self, plaintext: str) -> str:
        # 加密流程：plaintext(utf-8) -> RSA(PKCS#1 v1.5) -> Base64
        # 注：PKCS#1 v1.5 单次可加密明文字节数受 key_size 限制（key_size_bytes - 11）
        if self._pubkey is None or padding is None:
            raise RuntimeError("缺少依赖 cryptography，无法进行 RSA 加密；请先安装 requirements.txt 依赖。")
        data = plaintext.encode("utf-8")
        key_size_bytes = self._pubkey.key_size // 8
        max_len = key_size_bytes - 11
        if len(data) > max_len:
            raise ValueError(
                f"明文过长：{len(data)} 字节；当前 {self._pubkey.key_size} 位 RSA 在 PKCS#1 v1.5 下最多 {max_len} 字节。"
            )
        ct = self._pubkey.encrypt(data, padding.PKCS1v15())
        return base64.b64encode(ct).decode("ascii")


class VappSigner:
    def __init__(self, salt: str = VAPP_SIGNATURE_SALT):
        self.salt = salt

    @staticmethod
    def _request_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _timestamp_ms() -> str:
        return str(int(time.time() * 1000))

    def signature(self, path: str, session_id: str, request_id: str, timestamp_ms: str, tenant_id: str) -> str:
        # vapp 侧 X-SIGNATURE 算法（已在 script/dachao_bak 中验证过）：SHA256(path && sessionId && requestId && timestamp && salt && tenantId)
        preimage = f"{path}&&{session_id}&&{request_id}&&{timestamp_ms}&&{self.salt}&&{tenant_id}"
        return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


class TmuyunPassportClient:
    BASE_URL = "https://passport.tmuyun.com"

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        # 避免系统代理/环境变量导致请求“卡住”
        self.session.trust_env = False

    @staticmethod
    def _build_signature_placeholder(path: str, request_id: str, salt: str = "") -> str:
        # 说明：
        # - passport 的 X-SIGNATURE 在抓包中存在，但不同应用/版本可能算法不同。
        # - 这里实现的是“占位版 64hex”，仅用于让请求具备合法格式。
        # - 如果服务端严格校验，需要你按抓包还原真实算法/盐值。
        preimage = f"{path}&&{request_id}"
        if salt:
            preimage = f"{preimage}&&{salt}"
        return hashlib.sha256(preimage.encode("utf-8")).hexdigest()

    def credential_auth(
        self,
        phone_number: str,
        password_encrypted: str,
        client_id: str,
        user_agent: str,
        cookies: str = "",
        signature_salt: str = "",
        account_name: str = "",
        timeout: int = 30,
    ) -> str:
        # passport 账号密码登录第一步：拿到 authorization_code（登录 code）
        path = "/web/oauth/credential_auth"
        url = f"{self.BASE_URL}{path}"
        request_id = str(uuid.uuid4())
        signature = self._build_signature_placeholder(path, request_id, salt=signature_salt)

        headers = {
            "User-Agent": user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "X-REQUEST-ID": request_id,
            "X-SIGNATURE": signature,
        }
        if cookies:
            headers["Cookie"] = cookies

        data = {
            "client_id": client_id,
            "password": password_encrypted,
            "phone_number": phone_number,
        }

        payload = request_json(
            self.session,
            method="POST",
            url=url,
            headers=headers,
            data=data,
            timeout=timeout,
            account_name=account_name,
        )
        if payload.get("code") != 0:
            raise RuntimeError(f"credential_auth failed: {payload}")
        code = (
            payload.get("data", {})
            .get("authorization_code", {})
            .get("code", "")
        )
        if not code:
            raise RuntimeError(f"credential_auth missing authorization code: {payload}")
        return str(code)


class TmuyunVappClient:
    BASE_URL = "https://vapp.tmuyun.com"

    def __init__(self, session: Optional[requests.Session] = None, signer: Optional[VappSigner] = None):
        self.session = session or requests.Session()
        self.session.trust_env = False
        self.signer = signer or VappSigner()

    @staticmethod
    def _random_session_seed() -> str:
        # iOS 抓包里像 24 位 hex；用于 X-SESSION-ID（登录前阶段的签名参与与追踪）
        return uuid.uuid4().hex[:24]

    def _signed_headers(
        self,
        *,
        path: str,
        session_id: str,
        tenant_id: str,
        account_id: str = "",
        user_agent: str = "",
        cookies: str = "",
        extra: Optional[Dict[str, str]] = None,
    ) -> Dict[str, str]:
        # vapp 大多数接口都需要：
        # - X-SESSION-ID / X-REQUEST-ID / X-TIMESTAMP
        # - X-SIGNATURE（由 VappSigner 生成）
        request_id = self.signer._request_id()
        timestamp = self.signer._timestamp_ms()
        signature = self.signer.signature(path, session_id, request_id, timestamp, tenant_id)

        headers = {
            "User-Agent": user_agent,
            "X-TIMESTAMP": timestamp,
            "X-SESSION-ID": session_id,
            "X-SIGNATURE": signature,
            "X-TENANT-ID": tenant_id,
            "X-REQUEST-ID": request_id,
            "Accept-Language": "zh-Hans-CN;q=1, en-CN;q=0.9",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        if account_id:
            headers["X-ACCOUNT-ID"] = account_id
        if cookies:
            headers["Cookie"] = cookies
        if extra:
            headers.update(extra)
        return headers

    def login_with_code(
        self,
        code: str,
        tenant_id: str,
        user_agent: str,
        cookies: str = "",
        session_seed: str = "",
        account_name: str = "",
        timeout: int = 30,
    ) -> DachaoLoginContext:
        path = "/api/zbtxz/login"
        url = f"{self.BASE_URL}{path}"
        seed = session_seed or self._random_session_seed()
        # 注意：
        # - 这里的 seed 是“登录前请求头里的 X-SESSION-ID”，一般来自配置/抓包；
        # - 登录成功后，接口返回 data.session.id 才是“登录态 session”，后续接口会用 ctx.session_id。
        headers = self._signed_headers(
            path=path,
            session_id=seed,
            tenant_id=tenant_id,
            account_id="",
            user_agent=user_agent,
            cookies=cookies,
            extra={"X-Auth-Token": "", "YI-TOKEN": ""},
        )

        payload = request_json(
            self.session,
            method="POST",
            url=url,
            headers=headers,
            data={"code": code},
            timeout=timeout,
            account_name=account_name,
        )
        if payload.get("code") != 0:
            raise RuntimeError(f"vapp login failed: {payload}")

        data = payload.get("data", {}) or {}
        session_info = data.get("session", {}) or {}
        account_info = data.get("account", {}) or {}

        session_id = str(session_info.get("id") or "")
        account_id = str(account_info.get("id") or "")
        nick_name = str(account_info.get("nick_name") or "")
        avatar_url = str(account_info.get("image_url") or "")
        mobile = str(account_info.get("mobile") or account_info.get("phone_number") or "")

        if not session_id or not account_id:
            raise RuntimeError(f"vapp login missing session/account: {payload}")

        return DachaoLoginContext(
            session_id=session_id,
            account_id=account_id,
            tenant_id=str(tenant_id),
            nick_name=nick_name,
            avatar_url=avatar_url,
            mobile=mobile,
        )

    def mypage_list(
        self,
        ctx: DachaoLoginContext,
        user_agent: str,
        cookies: str = "",
        account_name: str = "",
        timeout: int = 30,
    ) -> Dict[str, Any]:
        path = "/api/myPage/list"
        url = f"{self.BASE_URL}{path}"
        headers = self._signed_headers(
            path=path,
            session_id=ctx.session_id,
            tenant_id=ctx.tenant_id,
            account_id=ctx.account_id,
            user_agent=user_agent,
            cookies=cookies,
            extra={"X-Auth-Token": "", "YI-TOKEN": ""},
        )
        return request_json(
            self.session,
            method="GET",
            url=url,
            headers=headers,
            timeout=timeout,
            account_name=account_name,
        )

    def buoy_list(
        self,
        ctx: DachaoLoginContext,
        user_agent: str,
        cookies: str = "",
        account_name: str = "",
        timeout: int = 30,
    ) -> Dict[str, Any]:
        path = "/api/buoy/list"
        url = f"{self.BASE_URL}{path}"
        headers = self._signed_headers(
            path=path,
            session_id=ctx.session_id,
            tenant_id=ctx.tenant_id,
            account_id=ctx.account_id,
            user_agent=user_agent,
            cookies=cookies,
            extra={"X-Auth-Token": "", "YI-TOKEN": ""},
        )
        return request_json(
            self.session,
            method="GET",
            url=url,
            headers=headers,
            timeout=timeout,
            account_name=account_name,
        )

    def report_read_time(
        self,
        ctx: DachaoLoginContext,
        channel_article_id: str,
        read_time_ms: int,
        user_agent: str,
        cookies: str = "",
        account_name: str = "",
        timeout: int = 30,
    ) -> Dict[str, Any]:
        path = "/api/article/read_time"
        url = f"{self.BASE_URL}{path}"
        params = {
            "channel_article_id": str(channel_article_id),
            "is_end": "1",
            "read_time": str(read_time_ms),
        }
        headers = self._signed_headers(
            path=path,
            session_id=ctx.session_id,
            tenant_id=ctx.tenant_id,
            account_id=ctx.account_id,
            user_agent=user_agent,
            cookies=cookies,
            extra={"X-Auth-Token": "", "YI-TOKEN": ""},
        )
        return request_json(
            self.session,
            method="GET",
            url=url,
            headers=headers,
            params=params,
            timeout=timeout,
            account_name=account_name,
        )


class AihogeClient:
    BASE_URL = "https://m.aihoge.com"

    def __init__(
        self,
        *,
        member_header: str,
        account_id: str,
        session_id: str,
        cookies: str = "",
        user_agent: str = "",
        redeem_member: str = "",
        redeem_cookies: str = "",
        redeem_user_agent: str = "",
        account_name: str = "",
    ):
        self.session = requests.Session()
        self.session.trust_env = False
        self.member_header = member_header
        self.account_id = account_id
        self.session_id = session_id
        self.cookies = cookies
        self.user_agent = user_agent
        self.redeem_member = redeem_member
        self.redeem_cookies = redeem_cookies
        self.redeem_user_agent = redeem_user_agent
        self.account_name = account_name
        self._rsa = RsaEncryptor()
        self._captcha_verified = False

    def _common_headers(self, *, limit_id: str, referer_url: str) -> Dict[str, str]:
        # aihoge 侧通用头：
        # - member：由 /api/memberhy/tm/signature 构建得到（后续所有请求都要带）
        # - accountId / sessionId：来自 vapp 登录返回的 account.id / session.id
        # - Limit：对应活动 tid（签到/阅读有礼的 tid）
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "HTTP-X-H5-VERSION": "1",
            "X-CLIENT-VERSION": "1314",
            "X-DEVICE-SIGN": "xsb_hn",
            "X-DEVICE-ID": "000",
            "Limit": limit_id,
            "Referer": referer_url,
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Dest": "empty",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "accountId": self.account_id,
            "sessionId": self.session_id,
            "member": self.member_header,
        }
        if self.cookies:
            headers["Cookie"] = self.cookies
        return headers

    # -------- 签到 --------

    def sign_in(self, activity_id: str, sign_page_url: str) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/api/signhy/client/actSign/actSign"
        payload = {"activity_id": activity_id, "timestamp": str(int(time.time()))}
        # signhy 的 params 需要 RSA(PKCS#1 v1.5) + Base64
        encrypted = self._rsa.encrypt_base64_pkcs1v15(_safe_json_dumps(payload))

        headers = self._common_headers(limit_id=activity_id, referer_url=sign_page_url)
        headers.update({"Content-Type": "application/json;charset=utf-8", "Origin": "https://m.aihoge.com"})

        return request_json(
            self.session,
            method="POST",
            url=url,
            headers=headers,
            json_body={"params": encrypted},
            timeout=30,
            account_name=self.account_name,
        )

    # -------- 阅读任务 --------

    def get_news_list(self, news_tid: str, referer_url: str) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/api/newshy/api/client/news/list/{news_tid}"
        headers = self._common_headers(limit_id=news_tid, referer_url=referer_url)
        return request_json(
            self.session,
            method="GET",
            url=url,
            headers=headers,
            timeout=30,
            account_name=self.account_name,
        )

    @staticmethod
    def extract_articles(news_list_resp: Dict[str, Any]) -> List[Dict[str, Any]]:
        data = news_list_resp.get("data", [])
        if not data:
            return []
        first = data[0] or {}
        limit = first.get("limit", {}) or {}
        column_set = limit.get("column_set", {}) or {}
        column_list = column_set.get("column_list", []) or []
        if not column_list:
            return []
        articles = (column_list[0] or {}).get("data", []) or []
        return [a for a in articles if isinstance(a, dict)]

    @staticmethod
    def extract_award_activity_id(news_list_resp: Dict[str, Any]) -> str:
        data = news_list_resp.get("data", [])
        if not data:
            return ""
        first = data[0] or {}
        limit = first.get("limit", {}) or {}
        rtc = limit.get("read_task_config", {}) or {}
        return str(rtc.get("awardActivityId") or "")

    def _read_article_internal(
        self,
        *,
        news_tid: str,
        item_id: str,
        referer_url: str,
        tn_x: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/api/newshy/api/client/news/readArticle"
        payload: Dict[str, Any] = {"news_id": news_tid, "item_id": item_id, "timestamp": str(int(time.time()))}
        if tn_x is not None and request_id is not None:
            payload["tn_x"] = int(tn_x)
            payload["request_id"] = str(request_id)
        encrypted = self._rsa.encrypt_base64_pkcs1v15(_safe_json_dumps(payload))

        headers = self._common_headers(limit_id=news_tid, referer_url=referer_url)
        headers.update(
            {
                "Content-Type": "application/json;charset=utf-8",
                "Origin": "https://m.aihoge.com",
                "Cache-Control": "no-cache",
                "Pragma": "no-cache",
            }
        )
        return request_json(
            self.session,
            method="POST",
            url=url,
            headers=headers,
            json_body={"params": encrypted},
            timeout=30,
            account_name=self.account_name,
        )

    def get_captcha(self, news_tid: str, referer_url: str) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/api/newshy/api/client/news/getTnCode"
        headers = self._common_headers(limit_id=news_tid, referer_url=referer_url)
        headers["X-Requested-With"] = "XMLHttpRequest"
        return request_json(
            self.session,
            method="GET",
            url=url,
            headers=headers,
            params={"t": str(random.random())},
            timeout=30,
            account_name=self.account_name,
        )

    def complete_read_task(self, news_tid: str, item_id: str, referer_url: str) -> Dict[str, Any]:
        if self._captcha_verified:
            return self._read_article_internal(news_tid=news_tid, item_id=item_id, referer_url=referer_url)

        result = self._read_article_internal(news_tid=news_tid, item_id=item_id, referer_url=referer_url)
        need_captcha = result.get("error_code") == "INVALID_CODE" or result.get("error_message") == "验证码错误"
        if not need_captcha:
            if result.get("success") == 1:
                self._captcha_verified = True
            return result

        if calculate_slide_offset is None:
            logger.warning("缺少滑块验证码偏移量计算能力（numpy/Pillow），无法自动处理验证码")
            return result

        captcha = self.get_captcha(news_tid=news_tid, referer_url=referer_url)
        request_id = captcha.get("request_id")
        img_url = captcha.get("img")
        if not request_id or not img_url:
            return result

        tn_x = calculate_slide_offset(img_url)
        if tn_x is None:
            return result

        time.sleep(random.uniform(3, 5))
        result = self._read_article_internal(
            news_tid=news_tid, item_id=item_id, referer_url=referer_url, tn_x=tn_x, request_id=request_id
        )
        if result.get("success") == 1:
            self._captcha_verified = True
        return result

    @staticmethod
    def extract_channel_article_id(link: str) -> str:
        if not link:
            return ""
        try:
            parsed = urlparse(link)
            params = parse_qs(parsed.query)
            return str((params.get("id") or [""])[0] or "")
        except Exception:
            return ""

    # -------- 抽奖 --------

    def get_lottery_info(self, lottery_id: str, limit_id: str, referer_url: str) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/api/lotteryhy/designh5/client/activity/{lottery_id}"
        headers = self._common_headers(limit_id=limit_id, referer_url=referer_url)
        return request_json(
            self.session,
            method="GET",
            url=url,
            headers=headers,
            timeout=30,
            account_name=self.account_name,
        )

    def get_remain_counts(self, lottery_id: str, limit_id: str, referer_url: str) -> int:
        data = self.get_lottery_info(lottery_id=lottery_id, limit_id=limit_id, referer_url=referer_url)
        try:
            return int((data.get("response") or {}).get("remain_counts") or 0)
        except Exception:
            return 0

    def draw_lottery(self, lottery_id: str, limit_id: str, referer_url: str) -> Dict[str, Any]:
        url = f"{self.BASE_URL}/api/lotteryhy/api/client/cj/awd/drw/{lottery_id}"
        headers = self._common_headers(limit_id=limit_id, referer_url=referer_url)
        headers.update(
            {"Content-Type": "application/json;charset=utf-8", "Origin": "https://m.aihoge.com", "Content-Length": "0"}
        )
        return request_json(
            self.session,
            method="POST",
            url=url,
            headers=headers,
            timeout=30,
            account_name=self.account_name,
        )

    def redeem_red_packet(self, code: str) -> Dict[str, Any]:
        """
        兑换现金红包（抽奖 type=3 时返回的 code）。

        对应你给的 Loon 脚本：
        POST https://m.aihoge.com/api/lotteryhy/api/client/cj/send/pak
        body: {"code": "..."}

        关键点：
        - headers.member 必须使用「兑换 member」（通常 source=wechat）
        - X-DEVICE-SIGN=wechat、Limit=default、Referer 带 code
        """
        if not code:
            return {"success": False, "error": "missing_code"}
        if not self.redeem_member:
            return {"success": False, "error": "missing_redeem_member"}

        url = f"{self.BASE_URL}/api/lotteryhy/api/client/cj/send/pak"
        headers: Dict[str, str] = {
            "Accept": "application/json, text/plain, */*",
            "HTTP-X-H5-VERSION": "1",
            "Limit": "default",
            "X-DEVICE-SIGN": "wechat",
            "X-DEVICE-ID": "000",
            "X-CLIENT-VERSION": "1314",
            "Origin": "https://m.aihoge.com",
            "Content-Type": "application/json;charset=utf-8",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "Referer": (
                "https://m.aihoge.com/lottery/awardBonus/drawRedPacket"
                "?title=%E9%A2%86%E5%8F%96%E7%BA%A2%E5%8C%85"
                f"&code={code}"
            ),
            "User-Agent": self.redeem_user_agent or self.user_agent,
            "member": self.redeem_member,
        }

        cookie = self.redeem_cookies or self.cookies
        if cookie:
            headers["Cookie"] = cookie

        return request_json(
            self.session,
            method="POST",
            url=url,
            headers=headers,
            json_body={"code": code},
            timeout=30,
            account_name=self.account_name,
        )

    def redeem_red_packet_with_retry(
        self,
        code: str,
        *,
        max_attempts: int = 3,
        min_delay_s: float = 1.5,
        max_delay_s: float = 3.5,
    ) -> Dict[str, Any]:
        """
        兑换红包并在“无效兑换码”时短暂重试。

        说明：
        - 部分场景下抽奖返回的 code 需要稍等生效，立即兑换会返回 428:无效兑换码。
        - 重试仅针对该类短暂错误，避免对真正失败的请求反复提交。
        """
        attempts = max(1, int(max_attempts))
        last_resp: Dict[str, Any] = {}

        for idx in range(1, attempts + 1):
            resp = self.redeem_red_packet(code)
            last_resp = resp
            meta = interpret_redeem_response(resp)
            if meta["ok"]:
                return resp

            code_text = str(meta.get("code") or "")
            message = str(meta.get("message") or "")
            should_retry = code_text == "428" or "无效兑换码" in message
            if not should_retry or idx >= attempts:
                return resp

            delay = random.uniform(min_delay_s, max_delay_s)
            if self.account_name:
                logger.info(f"[{self.account_name}] 兑换码暂不可用，{delay:.2f} 秒后重试({idx}/{attempts})")
            time.sleep(delay)

        return last_resp

    @staticmethod
    def parse_lottery_result(result: Dict[str, Any]) -> str:
        if result.get("error"):
            return f"抽奖失败: {result.get('error')}"
        award_name = result.get("award_name", "未知奖品")
        award_content = result.get("award_content", "") or award_name
        award_type = result.get("type", 0)
        if award_type == 5:
            points = result.get("prize_integral", 0)
            return f"{award_content} (+{points}积分)"
        if award_type == 3:
            money = result.get("money", 0)
            return f"{award_content} (+{money}元)"
        return award_content
class AihogeMemberBuilder:
    BASE_URL = "https://m.aihoge.com"

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.trust_env = False

    @staticmethod
    def _signature_placeholder(account_id: str, session_id: str, timestamp_ms: str, sign: str, salt: str = "") -> str:
        # 说明：
        # - /api/memberhy/tm/signature 的 body 里有 signature 字段（抓包可见），算法可能与 vapp 不同。
        # - 这里同样提供“占位版 64hex”，仅保证字段格式；如校验严格，需要还原真实算法/盐值。
        preimage = f"{account_id}&&{session_id}&&{timestamp_ms}&&{sign}"
        if salt:
            preimage = f"{preimage}&&{salt}"
        return hashlib.sha256(preimage.encode("utf-8")).hexdigest()

    def build_member(
        self,
        *,
        ctx: DachaoLoginContext,
        sign_tid: str,
        sign_page_url: str,
        user_agent: str,
        cookies: str = "",
        signature_salt: str = "",
        account_name: str = "",
        timeout: int = 30,
    ) -> Tuple[str, Dict[str, Any]]:
        # member 构建：让 aihoge 识别 vapp 的登录态（account/session）并下发 member token 组
        # 对应你抓包的「1.3 构建 member 信息」：
        # POST https://m.aihoge.com/api/memberhy/tm/signature
        url = f"{self.BASE_URL}/api/memberhy/tm/signature"
        timestamp_ms = str(int(time.time() * 1000))
        signature = self._signature_placeholder(
            account_id=ctx.account_id,
            session_id=ctx.session_id,
            timestamp_ms=timestamp_ms,
            sign="xsb_hn",
            salt=signature_salt,
        )

        payload = {
            "mobile": "1",
            "accountId": ctx.account_id,
            "user": {
                "id": ctx.account_id,
                "realname": "",
                "image_url": ctx.avatar_url,
                "nick_name": ctx.nick_name,
                "idcard": "",
                "is_face_verify": False,
            },
            "signature": signature,
            "sessionId": ctx.session_id,
            "timestamp": timestamp_ms,
            "login": "1",
            "sign": "xsb_hn",
        }

        headers = {
            "User-Agent": user_agent,
            "Accept": "application/json, text/plain, */*",
            "HTTP-X-H5-VERSION": "1",
            "Limit": sign_tid,
            "Referer": sign_page_url,
            "X-DEVICE-SIGN": "xsb_hn",
            "Origin": "https://m.aihoge.com",
            "X-DEVICE-ID": "000",
            "X-CLIENT-VERSION": "1314",
            "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            "Content-Type": "application/json;charset=utf-8",
        }
        if cookies:
            headers["Cookie"] = cookies

        member_info = request_json(
            self.session,
            method="POST",
            url=url,
            headers=headers,
            json_body=payload,
            timeout=timeout,
            account_name=account_name,
        )

        # member 请求头需要 URL 编码 nick_name（抓包表现为 %E5...）
        member_header = {
            "id": member_info.get("id", ""),
            "black": int(member_info.get("black", 0) or 0),
            "btoken": member_info.get("btoken", ""),
            "expire": int(member_info.get("expire", 0) or 0),
            "token": member_info.get("token", ""),
            "source": member_info.get("source", "xsb_hn"),
            "mobile": member_info.get("mobile", ctx.mobile),
            "mark": member_info.get("mark", ctx.mobile),
            "mtoken": member_info.get("mtoken", ""),
            "stoken": member_info.get("stoken", ""),
            "nick_name": quote(str(member_info.get("nick_name") or ctx.nick_name), safe=""),
            "avatar": member_info.get("avatar", ctx.avatar_url),
        }
        return _safe_json_dumps(member_header), member_info


def discover_sign_page_and_tid(mypage_resp: Dict[str, Any]) -> Tuple[str, str]:
    """
    从 /api/myPage/list 返回中提取签到页面 URL 与 tid。

    对应你抓包的「2.1 获取签到任务信息」：
    GET https://vapp.tmuyun.com/api/myPage/list
    从 data.new_list.records[] 中找到“签到”的 url，并解析 query 里的 tid。
    """
    data = (mypage_resp.get("data") or {}) if isinstance(mypage_resp, dict) else {}
    new_list = (data.get("new_list") or {}) if isinstance(data, dict) else {}
    records = (new_list.get("records") or []) if isinstance(new_list, dict) else []

    for rec in records:
        if not isinstance(rec, dict):
            continue
        # list_type=9 对应“签到”（抓包示例）
        if rec.get("list_type") == 9 or rec.get("list_title") == "签到" or rec.get("doc_title") == "签到":
            url = str(rec.get("url") or rec.get("web_view_url") or "")
            tid = _parse_tid_from_url(url)
            if url and tid:
                return url, tid
    return "", ""


def discover_news_read_tid(buoy_resp: Dict[str, Any]) -> Tuple[str, str]:
    """
    从 /api/buoy/list 返回中提取阅读有礼 entryLink 与 tid。

    对应你抓包的「3.1 获取阅读有礼活动信息」：
    GET https://vapp.tmuyun.com/api/buoy/list
    从 data.new_down.icon_list[0].turn_to.entryLink 解析 tid。
    """
    data = (buoy_resp.get("data") or {}) if isinstance(buoy_resp, dict) else {}
    new_down = (data.get("new_down") or {}) if isinstance(data, dict) else {}
    icon_list = (new_down.get("icon_list") or []) if isinstance(new_down, dict) else []

    for icon in icon_list:
        if not isinstance(icon, dict):
            continue
        turn_to = icon.get("turn_to") or {}
        if not isinstance(turn_to, dict):
            continue
        entry = str(turn_to.get("entryLink") or turn_to.get("url") or "")
        tid = _parse_tid_from_url(entry)
        if entry and tid:
            return entry, tid
    return "", ""


def login_build_clients(
    cfg: NewDachaoAccountConfig, *, account_name: str = ""
) -> Tuple[str, DachaoLoginContext, str, str, str, AihogeClient]:
    """
    完整流程：passport -> vapp -> (discover sign tid) -> aihoge member -> AihogeClient

    Returns:
        (passport_code, ctx, sign_page_url, sign_tid, news_tid, aihoge_client)
    """
    passport = TmuyunPassportClient()
    vapp = TmuyunVappClient()

    name = account_name or cfg.account_name
    logger.info(f"[{name}] 开始登录：{_mask_mobile(cfg.phone_number)}")

    # Step 1) 账号密码登录：向 passport 申请 authorization_code（登录 code）
    #
    # 对应你抓包的「1.1 获取登陆code」：
    # POST https://passport.tmuyun.com/web/oauth/credential_auth
    #
    # 成功返回示例（字段路径）：
    #   data.authorization_code.code  ->  这里的 auth_code
    #
    # 说明：
    # - phone_number：手机号
    # - password_encrypted：抓包得到的“加密密码字符串”（不是明文密码）
    # - client_id：抓包中的 client_id（如 10048）
    # - cookies / signature_salt：可选；如服务端校验严格，需要按抓包补齐
    auth_code = passport.credential_auth(
        phone_number=cfg.phone_number,
        password_encrypted=cfg.password_encrypted,
        client_id=cfg.client_id,
        user_agent=cfg.user_agent,
        cookies=cfg.passport_cookies,
        signature_salt=cfg.passport_signature_salt,
        account_name=name,
    )

    # Step 2) 使用 authorization_code 换取登录态（session/account 等信息）
    #
    # 对应你抓包的「1.2 根据登陆code进行登陆，获取登陆信息」：
    # POST https://vapp.tmuyun.com/api/zbtxz/login
    #
    # 成功返回示例（字段路径）：
    # - data.session.id   -> ctx.session_id（后续 vapp 接口的 X-SESSION-ID）
    # - data.account.id   -> ctx.account_id（后续 vapp 接口的 X-ACCOUNT-ID / aihoge header 的 accountId）
    #
    # 说明：
    # - tenant_id：租户（抓包里 X-TENANT-ID，通常是 94）
    # - session_seed：登录前请求头里的 X-SESSION-ID（抓包里是类似 24 位 hex），这里从配置读取；
    #   注意它不同于登录成功后返回的 data.session.id。
    ctx = vapp.login_with_code(
        code=auth_code,
        tenant_id=cfg.tenant_id,
        user_agent=cfg.user_agent,
        cookies=cfg.vapp_cookies,
        session_seed=cfg.session_id,
        account_name=name,
    )

    # Step 3) 拉取「我的」页面模块列表，提取签到入口 url 与 tid
    mypage = vapp.mypage_list(ctx, user_agent=cfg.user_agent, cookies=cfg.vapp_cookies, account_name=name)
    sign_page_url, sign_tid = discover_sign_page_and_tid(mypage)
    if not sign_tid:
        raise RuntimeError(f"[{name}] 无法从 myPage/list 提取签到 tid: {mypage}")
    logger.info(f"[{name}] 获取签到活动tid: {sign_tid}")
    logger.info(f"[{name}] 签到页面: {sign_page_url}")

    # Step 4) 拉取浮标入口，尝试提取「阅读有礼」 entryLink 与 tid（可能为空）
    buoy = vapp.buoy_list(ctx, user_agent=cfg.user_agent, cookies=cfg.vapp_cookies, account_name=name)
    news_entry_url, news_tid = discover_news_read_tid(buoy)
    if news_tid:
        logger.info(f"[{name}] 获取阅读有礼tid: {news_tid}")
        logger.info(f"[{name}] 阅读有礼入口: {news_entry_url}")
    else:
        logger.info(f"[{name}] 未找到阅读有礼入口（可能账号无该浮标/活动未开启）")
    # news_tid 可为空（部分账号/版本可能无“阅读有礼”浮标）

    # Step 5) 用 vapp 的 account/session 构建 aihoge member（后续 aihoge 所有接口都需要 header: member）
    member_builder = AihogeMemberBuilder()
    member_header, _raw_member = member_builder.build_member(
        ctx=ctx,
        sign_tid=sign_tid,
        sign_page_url=sign_page_url or f"https://m.aihoge.com/h5?mark=sign@designh5&tid={sign_tid}&path=preview",
        user_agent=cfg.user_agent,
        cookies=cfg.aihoge_cookies,
        signature_salt=cfg.aihoge_signature_salt,
        account_name=name,
    )
    try:
        member_obj = json.loads(member_header)
        member_id = _mask_secret(member_obj.get("id", ""))
        expire = member_obj.get("expire", "")
        logger.info(f"[{name}] 构建member成功: id={member_id} expire={expire}")
    except Exception:
        logger.info(f"[{name}] 构建member成功")

    aihoge = AihogeClient(
        member_header=member_header,
        account_id=ctx.account_id,
        session_id=ctx.session_id,
        cookies=cfg.aihoge_cookies,
        user_agent=cfg.user_agent,
        redeem_member=cfg.redeem_member,
        redeem_cookies=cfg.redeem_cookies,
        redeem_user_agent=cfg.redeem_user_agent,
        account_name=name,
    )
    return auth_code, ctx, sign_page_url, sign_tid, news_tid, aihoge


def run_sign_flow(aihoge: AihogeClient, *, sign_tid: str, sign_page_url: str) -> Dict[str, Any]:
    return aihoge.sign_in(activity_id=sign_tid, sign_page_url=sign_page_url)


def run_sign_lottery_flow(
    aihoge: AihogeClient,
    *,
    sign_tid: str,
    sign_page_url: str,
    sign_lottery_id: str,
) -> Dict[str, Any]:
    # 签到抽奖：先查 remain_counts，再按次数调用抽奖接口
    if not sign_lottery_id:
        return {"lottery_id": "", "lottery_count": 0, "lottery_results": []}

    referer_url = sign_page_url or f"https://m.aihoge.com/h5?mark=sign@designh5&tid={sign_tid}&path=index&autoSign=true"
    remain = 0
    try:
        remain = aihoge.get_remain_counts(lottery_id=sign_lottery_id, limit_id=sign_tid, referer_url=referer_url)
    except Exception:
        remain = 0

    results: List[str] = []
    for i in range(remain):
        try:
            res = aihoge.draw_lottery(lottery_id=sign_lottery_id, limit_id=sign_tid, referer_url=referer_url)
            prize_desc = aihoge.parse_lottery_result(res)
            # 现金红包：拿到 code 后自动兑换
            if res.get("type") == 3:
                redeem_code = str(res.get("code") or "")
                redeem_resp = aihoge.redeem_red_packet_with_retry(redeem_code)
                redeem_meta = interpret_redeem_response(redeem_resp)
                if redeem_meta["ok"]:
                    prize_desc = f"{prize_desc} ({'已领取' if redeem_meta['already_received'] else '已兑换'})"
                else:
                    err = redeem_meta.get("message") or "未知错误"
                    code_text = redeem_meta.get("code") or ""
                    suffix = f"{code_text}:{err}" if code_text else err
                    prize_desc = f"{prize_desc} (兑换失败: {suffix})"
            results.append(prize_desc)
        except Exception as e:
            results.append(f"抽奖失败: {e}")
        if i < remain - 1:
            time.sleep(random.uniform(1.0, 3.0))

    return {"lottery_id": sign_lottery_id, "lottery_count": remain, "lottery_results": results}


def run_read_flow(
    aihoge: AihogeClient,
    vapp: TmuyunVappClient,
    ctx: DachaoLoginContext,
    *,
    news_tid: str,
    news_entry_url: str,
    vapp_user_agent: str,
    vapp_cookies: str = "",

    read_delay_range_s: Tuple[float, float] = (20.0, 30.0),
    sleep_enabled: bool = True,
    account_name: str = "",
) -> Dict[str, Any]:
    # 阅读任务流程：
    # 1) 拉取阅读列表（news/list/{tid}）
    # 2) 对未完成的文章调用 readArticle（params RSA）
    # 3) 按随机时长 sleep 后调用 vapp read_time 上报阅读时间
    # 4) 如果列表中包含 awardActivityId，则进行阅读抽奖
    if not news_tid:
        return {"total": 0, "completed": 0, "lottery_id": "", "lottery_count": 0, "lottery_results": []}

    referer_url = news_entry_url or f"https://m.aihoge.com/h5?mark=news-read@designh5&tid={news_tid}&path=index"
    news_list = aihoge.get_news_list(news_tid=news_tid, referer_url=referer_url)
    articles = aihoge.extract_articles(news_list)
    award_activity_id = aihoge.extract_award_activity_id(news_list)
    if account_name and award_activity_id:
        logger.info(f"[{account_name}] 阅读抽奖活动ID: {award_activity_id}")

    candidates = []
    for a in articles:
        # 兼容不同字段：is_read==1 已读；没有则视为未读
        if a.get("is_read") == 1:
            continue
        candidates.append(a)

    completed = 0

    if account_name:
        if not candidates:
            logger.info(f"[{account_name}] 没有未完成的阅读任务")
        else:
            logger.info(f"[{account_name}] 发现 {len(candidates)} 个未完成的阅读任务")

    for idx, a in enumerate(candidates, 1):
        item_id = str(a.get("item_id") or "")
        title = str(a.get("title") or "")
        link = str(a.get("link") or a.get("link_url") or "")
        if not item_id:
            continue

        if account_name:
            logger.info(f"[{account_name}] 正在执行阅读任务 ({idx}/{len(candidates)}): {title[:30]}...")
        resp = aihoge.complete_read_task(news_tid=news_tid, item_id=item_id, referer_url=referer_url)
        if resp.get("success") == 1:
            completed += 1
            if account_name:
                task_turn = resp.get("task_turn")
                if task_turn is not None:
                    logger.info(f"[{account_name}] 阅读任务完成成功，当前进度: {task_turn}")
                else:
                    logger.info(f"[{account_name}] 阅读任务完成成功")
            delay_s = max(0.0, random.uniform(*read_delay_range_s))
            delay_ms = max(1000, int(delay_s * 1000))
            if sleep_enabled and delay_s > 0:
                if account_name:
                    logger.info(f"[{account_name}] 等待 {delay_s:.2f} 秒后上报阅读时间...")
                time.sleep(delay_s)
            else:
                # 调试模式可跳过等待，但仍要给 vapp/read_time 一个合理的 read_time 参数（避免 0）
                delay_ms = 1000
            channel_article_id = aihoge.extract_channel_article_id(link)
            if channel_article_id:
                try:
                    vapp.report_read_time(
                        ctx=ctx,
                        channel_article_id=channel_article_id,
                        read_time_ms=delay_ms,
                        user_agent=vapp_user_agent,
                        cookies=vapp_cookies,
                        account_name=account_name,
                    )
                except Exception:
                    # 上报失败不影响主流程
                    pass
        else:
            # click_quick 等错误时加点延迟
            error_code = resp.get("error_code", "")
            delay = random.uniform(2.0, 5.0)
            if account_name and error_code == "click_quick":
                logger.info(f"[{account_name}] 请求过快，等待 {delay:.2f} 秒后继续...")
            time.sleep(delay)

        if idx < len(candidates):
            time.sleep(random.uniform(2.0, 5.0))

    lottery_results: List[str] = []
    lottery_count = 0
    if award_activity_id:
        try:
            remain = aihoge.get_remain_counts(lottery_id=award_activity_id, limit_id=news_tid, referer_url=referer_url)
        except Exception:
            remain = 0
        lottery_count = remain
        for i in range(remain):
            try:
                res = aihoge.draw_lottery(lottery_id=award_activity_id, limit_id=news_tid, referer_url=referer_url)
                prize_desc = aihoge.parse_lottery_result(res)
                if res.get("type") == 3:
                    redeem_code = str(res.get("code") or "")
                    logger.info("获取到现金红包兑换码，准备自动兑换...")
                    redeem_resp = aihoge.redeem_red_packet_with_retry(redeem_code)
                    redeem_meta = interpret_redeem_response(redeem_resp)
                    if redeem_meta["ok"]:
                        prize_desc = f"{prize_desc} ({'已领取' if redeem_meta['already_received'] else '已兑换'})"
                    else:
                        err = redeem_meta.get("message") or "未知错误"
                        code_text = redeem_meta.get("code") or ""
                        suffix = f"{code_text}:{err}" if code_text else err
                        prize_desc = f"{prize_desc} (兑换失败: {suffix})"
                lottery_results.append(prize_desc)
            except Exception as e:
                lottery_results.append(f"抽奖失败: {e}")
            if i < remain - 1:
                time.sleep(random.uniform(1.0, 3.0))

    return {
        "total": len(candidates),
        "completed": completed,
        "lottery_id": award_activity_id,
        "lottery_count": lottery_count,
        "lottery_results": lottery_results,
    }
