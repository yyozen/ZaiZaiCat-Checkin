#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new Env('WPS天天领福利');
cron: 1 1 1 1 1
"""

"""
WPS 天天领福利活动脚本

当前支持：
- 自动发现“福利中心”活动入口
- 自动获取页面活动信息
- 自动执行打卡免费领会员
- 自动参与会员免费试用申请
- 自动执行天天抽奖

Author: Assistant
Date: 2026-03-11
"""

import json
import logging
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import requests

# 获取项目根目录
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from logging_utils import (
    bind_logger,
    configure_logging,
    get_logger,
    log_page_switch,
    log_task_result,
)
from notification import send_notification, NotificationSound


class DailyBenefitsAPI:
    """WPS 天天领福利活动接口封装"""

    MARKET_ACTIVITY_URL = "https://tiance.wps.cn/dce/exec/api/market/activity?rmsp=pv_vip_site"
    PAGE_INFO_URL = "https://personal-act.wps.cn/activity-rubik/activity/page_info"
    COMPONENT_ACTION_URL = "https://personal-act.wps.cn/activity-rubik/activity/component_action"

    MARKET_ACTIVITY_PAYLOAD = {
        "channel_code": "HYGW5004,GWHD5002",
        "version": "",
        "platform": 8,
        "device": 1,
        "hdid": "",
        "filter_info": {}
    }

    TARGET_TITLES = {"福利中心", "天天领福利"}

    def __init__(self, cookies: str, user_agent: Optional[str] = None):
        self.cookies = self._parse_cookies(cookies)
        self.user_agent = user_agent or (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
        )
        self.base_headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Content-Type": "application/json; charset=UTF-8",
            "sec-ch-ua-platform": '"macOS"',
            "sec-ch-ua": '"Not:A-Brand";v="99", "Brave";v="145", "Chromium";v="145"',
            "sec-ch-ua-mobile": "?0",
            "sec-gpc": "1",
            "accept-language": "zh-CN,zh;q=0.7",
            "origin": "https://personal-act.wps.cn",
            "referer": "https://personal-act.wps.cn/",
            "priority": "u=1, i"
        }
        configure_logging()
        self.logger = bind_logger(get_logger("daily_benefits.api"), page=DailyBenefitsTasks.page_name)

    @staticmethod
    def _parse_cookies(cookie_str: str) -> Dict[str, str]:
        """将 Cookie 字符串解析为字典"""
        cookies: Dict[str, str] = {}
        for item in cookie_str.split("; "):
            if "=" in item:
                key, value = item.split("=", 1)
                cookies[key] = value
        return cookies

    @staticmethod
    def _extract_error_message(result: Dict[str, Any]) -> str:
        """从返回结果中提取错误消息"""
        return result.get("msg") or result.get("message") or result.get("error") or "未知错误"

    @staticmethod
    def _is_auth_expired_message(message: str) -> bool:
        keywords = ("Token已过期", "ErrNotLogin", "userNotLogin", "未登录", "请重新登录")
        return any(keyword in str(message) for keyword in keywords)

    def _build_failure_result(self, payload: Dict[str, Any], default_error: str = "未知错误") -> Dict[str, Any]:
        error_message = self._extract_error_message(payload) or default_error
        result = {
            "success": False,
            "error": error_message
        }
        if (
            payload.get("code") == 2000000
            or payload.get("ext_msg") == "userNotLogin"
            or self._is_auth_expired_message(error_message)
        ):
            result["error_type"] = "token_expired"
        return result

    def _request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """统一请求入口"""
        request_headers = self.base_headers.copy()
        if headers:
            request_headers.update(headers)

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=request_headers,
                cookies=self.cookies,
                params=params,
                json=json_data,
                timeout=30
            )
            response.raise_for_status()
            return {
                "success": True,
                "data": response.json()
            }
        except requests.exceptions.RequestException as exc:
            return {
                "success": False,
                "error": f"网络请求失败: {exc}"
            }
        except ValueError as exc:
            return {
                "success": False,
                "error": f"响应解析失败: {exc}"
            }

    def get_market_activity(self) -> Dict[str, Any]:
        """获取市场活动数据"""
        self.logger.info("获取活动入口数据", extra={"step": "入口发现"})
        result = self._request(
            "POST",
            self.MARKET_ACTIVITY_URL,
            headers={
                "sec-fetch-site": "same-site",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty"
            },
            json_data=self.MARKET_ACTIVITY_PAYLOAD
        )

        if not result["success"]:
            return result

        payload = result["data"]
        if payload.get("result") != "ok":
            return self._build_failure_result(payload)

        return {
            "success": True,
            "data": payload
        }

    def get_benefit_portal(self) -> Dict[str, Any]:
        """从市场活动数据中提取福利中心入口"""
        market_result = self.get_market_activity()
        if not market_result["success"]:
            return market_result

        candidates: List[Dict[str, str]] = []
        self._collect_portal_candidates(market_result["data"], candidates)

        if not candidates:
            return {
                "success": False,
                "error": "未找到福利中心活动入口"
            }

        selected = None
        for candidate in candidates:
            if candidate["title"] in self.TARGET_TITLES:
                selected = candidate
                break

        if selected is None:
            selected = candidates[0]

        portal_info = self._parse_portal_link(selected["link"])
        if not portal_info["success"]:
            return portal_info

        portal_info["title"] = selected["title"]
        portal_info["pic"] = selected.get("pic", "")
        return portal_info

    def _collect_portal_candidates(self, node: Any, candidates: List[Dict[str, str]]) -> None:
        """递归收集包含 portal 链接的活动入口"""
        if isinstance(node, dict):
            link = node.get("link")
            title = node.get("title")
            if isinstance(link, str) and isinstance(title, str) and "/rubik2/portal/" in link:
                candidates.append({
                    "title": title,
                    "link": link,
                    "pic": node.get("pic", "")
                })

            for value in node.values():
                self._collect_portal_candidates(value, candidates)

        elif isinstance(node, list):
            for item in node:
                self._collect_portal_candidates(item, candidates)

    def _parse_portal_link(self, link: str) -> Dict[str, Any]:
        """解析活动 portal 链接"""
        try:
            parsed = urlparse(link)
            path_parts = [part for part in parsed.path.split("/") if part]
            portal_index = path_parts.index("portal")

            activity_number = path_parts[portal_index + 1]
            page_number = path_parts[portal_index + 2]

            query_params = parse_qs(parsed.query)
            filter_params = {
                key: values[0]
                for key, values in query_params.items()
                if values
            }

            return {
                "success": True,
                "link": link,
                "activity_number": activity_number,
                "page_number": page_number,
                "filter_params": filter_params
            }
        except (ValueError, IndexError) as exc:
            return {
                "success": False,
                "error": f"活动链接解析失败: {exc}"
            }

    def get_page_info(self, portal_info: Dict[str, Any]) -> Dict[str, Any]:
        """获取页面全部活动信息"""
        self.logger.info("获取页面活动信息", extra={"step": "页面信息"})
        activity_number = portal_info["activity_number"]
        page_number = portal_info["page_number"]
        filter_params = portal_info.get("filter_params", {})

        result = self._request(
            "GET",
            self.PAGE_INFO_URL,
            headers={
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
                "referer": portal_info["link"]
            },
            params={
                "activity_number": activity_number,
                "page_number": page_number,
                "filter_params": json.dumps(filter_params, ensure_ascii=False, separators=(",", ":"))
            }
        )

        if not result["success"]:
            return result

        payload = result["data"]
        if payload.get("result") != "ok":
            return self._build_failure_result(payload)

        return {
            "success": True,
            "data": payload
        }

    def get_member_trial_info(self, page_info: Dict[str, Any]) -> Dict[str, Any]:
        """从总活动返回数据中提取会员免费试用模块"""
        data_list = page_info.get("data", [])
        fallback_item: Optional[Dict[str, Any]] = None

        for item in data_list:
            if not isinstance(item, dict):
                continue

            divide_prize = item.get("divide_prize")
            if not isinstance(divide_prize, dict):
                continue

            details = divide_prize.get("divide_prize_details") or []
            if not details:
                continue

            if fallback_item is None:
                fallback_item = item

            if any("会员" in str(detail.get("title", "")) for detail in details):
                return {
                    "success": True,
                    "component_number": item.get("number", ""),
                    "component_node_id": item.get("component_node_id", ""),
                    "remain_times": divide_prize.get("remain_times", 0),
                    "latest_result": divide_prize.get("latest_result", ""),
                    "join_reach_limit": divide_prize.get("join_reach_limit", False),
                    "details": details,
                    "raw_data": divide_prize
                }

        if fallback_item is not None:
            divide_prize = fallback_item.get("divide_prize", {})
            return {
                "success": True,
                "component_number": fallback_item.get("number", ""),
                "component_node_id": fallback_item.get("component_node_id", ""),
                "remain_times": divide_prize.get("remain_times", 0),
                "latest_result": divide_prize.get("latest_result", ""),
                "join_reach_limit": divide_prize.get("join_reach_limit", False),
                "details": divide_prize.get("divide_prize_details") or [],
                "raw_data": divide_prize
            }

        return {
            "success": False,
            "error": "未找到会员免费试用模块"
        }

    def sign_up_member_trial(
        self,
        portal_info: Dict[str, Any],
        component_number: str,
        component_node_id: str,
        cycle_id: str,
        session_id: str
    ) -> Dict[str, Any]:
        """执行会员免费试用申请"""
        csrf_token = self.cookies.get("act_csrf_token") or self.cookies.get("csrf")
        if not csrf_token:
            return {
                "success": False,
                "error": "Cookie 中缺少 act_csrf_token/csrf，无法提交试用申请"
            }

        payload = {
            "component_uniq_number": {
                "activity_number": portal_info["activity_number"],
                "page_number": portal_info["page_number"],
                "component_number": component_number,
                "component_node_id": component_node_id,
                "filter_params": {}
            },
            "component_type": 32,
            "component_action": "divide_prize.sign_up",
            "divide_prize": {
                "cycle_id": cycle_id,
                "session_id": session_id
            }
        }

        result = self._request(
            "POST",
            self.COMPONENT_ACTION_URL,
            headers={
                "Content-Type": "application/json",
                "x-act-csrf-token": csrf_token,
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
                "referer": (
                    f"https://personal-act.wps.cn/rubik2/portal/"
                    f"{portal_info['activity_number']}/{portal_info['page_number']}"
                )
            },
            json_data=payload
        )

        if not result["success"]:
            return result

        payload_data = result["data"]
        if payload_data.get("result") != "ok":
            return self._build_failure_result(payload_data)

        divide_prize = payload_data.get("data", {}).get("divide_prize", {})
        if divide_prize.get("success"):
            return {
                "success": True,
                "reason": divide_prize.get("reason", ""),
                "data": divide_prize
            }

        failure_result = {
            "success": False,
            "error": divide_prize.get("reason") or "试用申请失败",
            "data": divide_prize
        }
        if self._is_auth_expired_message(failure_result["error"]):
            failure_result["error_type"] = "token_expired"
        return failure_result

    def get_fragment_collect_info(self, page_info: Dict[str, Any]) -> Dict[str, Any]:
        """从总活动返回数据中提取打卡免费领会员模块"""
        data_list = page_info.get("data", [])
        fallback_item: Optional[Dict[str, Any]] = None

        for item in data_list:
            if not isinstance(item, dict):
                continue

            fragment_collect = item.get("fragment_collect")
            if not isinstance(fragment_collect, dict):
                continue

            sign_records = fragment_collect.get("sign_records") or []
            if not sign_records:
                continue

            if fallback_item is None:
                fallback_item = item

            server_time = item.get("server_time", 0)
            sign_date = (
                time.strftime("%Y-%m-%d", time.localtime(server_time))
                if server_time
                else time.strftime("%Y-%m-%d")
            )
            today_record = next(
                (record for record in sign_records if record.get("sign_date") == sign_date),
                None
            )

            if item.get("type") == 42 or today_record is not None:
                return {
                    "success": True,
                    "component_number": item.get("number", ""),
                    "component_node_id": item.get("component_node_id", ""),
                    "sign_date": sign_date,
                    "sign_series_id": fragment_collect.get("sign_series_id", ""),
                    "is_signed": (today_record or {}).get("sign_status") == "signed",
                    "today_record": today_record or {},
                    "sign_records": sign_records,
                    "raw_data": fragment_collect
                }

        if fallback_item is not None:
            fragment_collect = fallback_item.get("fragment_collect", {})
            sign_records = fragment_collect.get("sign_records") or []
            sign_date = sign_records[0].get("sign_date", time.strftime("%Y-%m-%d")) if sign_records else time.strftime("%Y-%m-%d")
            today_record = next(
                (record for record in sign_records if record.get("sign_date") == sign_date),
                None
            )
            return {
                "success": True,
                "component_number": fallback_item.get("number", ""),
                "component_node_id": fallback_item.get("component_node_id", ""),
                "sign_date": sign_date,
                "sign_series_id": fragment_collect.get("sign_series_id", ""),
                "is_signed": (today_record or {}).get("sign_status") == "signed",
                "today_record": today_record or {},
                "sign_records": sign_records,
                "raw_data": fragment_collect
            }

        return {
            "success": False,
            "error": "未找到打卡免费领会员模块"
        }

    def sign_in_fragment_collect(
        self,
        portal_info: Dict[str, Any],
        component_number: str,
        component_node_id: str,
        sign_date: str
    ) -> Dict[str, Any]:
        """执行打卡免费领会员签到"""
        csrf_token = self.cookies.get("act_csrf_token") or self.cookies.get("csrf")
        if not csrf_token:
            return {
                "success": False,
                "error": "Cookie 中缺少 act_csrf_token/csrf，无法执行打卡签到"
            }

        payload = {
            "component_uniq_number": {
                "activity_number": portal_info["activity_number"],
                "page_number": portal_info["page_number"],
                "component_number": component_number,
                "component_node_id": component_node_id,
                "filter_params": portal_info.get("filter_params", {})
            },
            "component_type": 42,
            "component_action": "fragment_collect.sign_in",
            "fragment_collect": {
                "sign_date": sign_date,
                "series_id": "",
                "is_new_sign_series": True
            }
        }

        result = self._request(
            "POST",
            self.COMPONENT_ACTION_URL,
            headers={
                "Content-Type": "application/json",
                "x-act-csrf-token": csrf_token,
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
                "referer": portal_info["link"]
            },
            json_data=payload
        )

        if not result["success"]:
            return result

        payload_data = result["data"]
        if payload_data.get("result") != "ok":
            return self._build_failure_result(payload_data)

        fragment_collect = payload_data.get("data", {}).get("fragment_collect", {})
        if fragment_collect.get("success"):
            return {
                "success": True,
                "reason": fragment_collect.get("reason", ""),
                "data": fragment_collect
            }

        failure_result = {
            "success": False,
            "error": fragment_collect.get("reason") or "打卡签到失败",
            "data": fragment_collect
        }
        if self._is_auth_expired_message(failure_result["error"]):
            failure_result["error_type"] = "token_expired"
        return failure_result

    @staticmethod
    def _pick_lottery_session(lottery_list: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """优先挑选进行中的抽奖场次"""
        for session in lottery_list:
            if (
                session.get("session_status") == "IN_PROGRESS"
                and session.get("stock_status") in {"IN_STOCK", "", None}
            ):
                return session

        for session in lottery_list:
            if session.get("session_status") == "IN_PROGRESS":
                return session

        return lottery_list[0] if lottery_list else None

    def get_daily_lottery_info(self, page_info: Dict[str, Any]) -> Dict[str, Any]:
        """从总活动返回数据中提取天天抽奖模块"""
        data_list = page_info.get("data", [])
        fallback_item: Optional[Dict[str, Any]] = None
        fallback_session: Optional[Dict[str, Any]] = None

        for item in data_list:
            if not isinstance(item, dict):
                continue

            lottery_v2 = item.get("lottery_v2")
            if not isinstance(lottery_v2, dict):
                continue

            lottery_list = lottery_v2.get("lottery_list") or []
            if not lottery_list:
                continue

            selected_session = self._pick_lottery_session(lottery_list)
            if selected_session is None:
                continue

            if fallback_item is None:
                fallback_item = item
                fallback_session = selected_session

            if selected_session.get("session_status") == "IN_PROGRESS":
                return {
                    "success": True,
                    "component_number": item.get("number", ""),
                    "component_node_id": item.get("component_node_id", ""),
                    "session_id": selected_session.get("session_id"),
                    "session_name": selected_session.get("session_name", ""),
                    "remain_times": selected_session.get("times", 0),
                    "stock_status": selected_session.get("stock_status", ""),
                    "share_times": lottery_v2.get("share_times", False),
                    "share_times_count": lottery_v2.get("share_times_count", 0),
                    "lottery_reward_list": selected_session.get("lottery_reward_list", []),
                    "raw_data": lottery_v2
                }

        if fallback_item is not None and fallback_session is not None:
            lottery_v2 = fallback_item.get("lottery_v2", {})
            return {
                "success": True,
                "component_number": fallback_item.get("number", ""),
                "component_node_id": fallback_item.get("component_node_id", ""),
                "session_id": fallback_session.get("session_id"),
                "session_name": fallback_session.get("session_name", ""),
                "remain_times": fallback_session.get("times", 0),
                "stock_status": fallback_session.get("stock_status", ""),
                "share_times": lottery_v2.get("share_times", False),
                "share_times_count": lottery_v2.get("share_times_count", 0),
                "lottery_reward_list": fallback_session.get("lottery_reward_list", []),
                "raw_data": lottery_v2
            }

        return {
            "success": False,
            "error": "未找到天天抽奖模块"
        }

    def exec_daily_lottery(
        self,
        portal_info: Dict[str, Any],
        component_number: str,
        component_node_id: str,
        session_id: Any
    ) -> Dict[str, Any]:
        """执行天天抽奖"""
        csrf_token = self.cookies.get("act_csrf_token") or self.cookies.get("csrf")
        if not csrf_token:
            return {
                "success": False,
                "error": "Cookie 中缺少 act_csrf_token/csrf，无法执行抽奖"
            }

        payload = {
            "component_uniq_number": {
                "activity_number": portal_info["activity_number"],
                "page_number": portal_info["page_number"],
                "component_number": component_number,
                "component_node_id": component_node_id,
                "filter_params": portal_info.get("filter_params", {})
            },
            "component_type": 45,
            "component_action": "lottery_v2.exec",
            "lottery_v2": {
                "session_id": session_id
            }
        }

        result = self._request(
            "POST",
            self.COMPONENT_ACTION_URL,
            headers={
                "Content-Type": "application/json",
                "x-act-csrf-token": csrf_token,
                "sec-fetch-site": "same-origin",
                "sec-fetch-mode": "cors",
                "sec-fetch-dest": "empty",
                "referer": portal_info["link"]
            },
            json_data=payload
        )

        if not result["success"]:
            return result

        payload_data = result["data"]
        if payload_data.get("result") != "ok":
            return self._build_failure_result(payload_data)

        lottery_v2 = payload_data.get("data", {}).get("lottery_v2", {})
        if lottery_v2.get("success"):
            return {
                "success": True,
                "reward_name": lottery_v2.get("reward_name", "未知奖品"),
                "reward_type": lottery_v2.get("reward_type", ""),
                "reward_id": lottery_v2.get("reward_id", 0),
                "order_id": lottery_v2.get("order_id", ""),
                "img": lottery_v2.get("img", ""),
                "data": lottery_v2
            }

        failure_result = {
            "success": False,
            "error": lottery_v2.get("send_msg") or "抽奖失败",
            "error_code": lottery_v2.get("error_code", 0),
            "data": lottery_v2
        }
        if self._is_auth_expired_message(failure_result["error"]):
            failure_result["error_type"] = "token_expired"
        return failure_result


class DailyBenefitsTasks:
    """天天领福利活动任务执行器"""

    page_name = "天天领福利"

    def __init__(self, config_path: str = None, enable_notification: bool = True, load_accounts: bool = True):
        if config_path is None:
            self.config_path = project_root / "config" / "token.json"
        else:
            self.config_path = Path(config_path)

        self.enable_notification = enable_notification
        self.logger = self._setup_logger()
        self.accounts: List[Dict[str, Any]] = []
        self.account_results: List[Dict[str, Any]] = []
        if load_accounts:
            self._init_accounts()

    def _setup_logger(self) -> logging.Logger:
        configure_logging()
        return bind_logger(get_logger("daily_benefits"), page=self.page_name)

    @staticmethod
    def _is_auth_expired_message(message: str) -> bool:
        keywords = ("Token已过期", "ErrNotLogin", "userNotLogin", "未登录", "请重新登录")
        return any(keyword in str(message) for keyword in keywords)

    def _init_accounts(self) -> None:
        """读取 WPS 账号配置"""
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")

        try:
            with open(self.config_path, "r", encoding="utf-8") as file:
                config_data = json.load(file)
        except json.JSONDecodeError as exc:
            raise ValueError(f"配置文件 JSON 解析失败: {exc}") from exc

        wps_config = config_data.get("wps", {})
        self.accounts = wps_config.get("accounts", [])

        if self.accounts:
            self.logger.info(f"成功加载 {len(self.accounts)} 个 WPS 账号")
        else:
            self.logger.warning("配置文件中没有找到 WPS 账号信息")

    def _process_member_trial(
        self,
        api: DailyBenefitsAPI,
        portal_result: Dict[str, Any],
        page_info: Dict[str, Any],
        account_name: str,
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """处理会员免费试用模块"""
        trial_logger = bind_logger(self.logger, account=account_name, step="会员试用")
        member_trial_result = api.get_member_trial_info(page_info)
        if not member_trial_result["success"]:
            message = member_trial_result["error"]
            result["member_trial"]["message"] = message
            return {
                "success": False,
                "message": message
            }

        details = member_trial_result["details"]
        remain_times = member_trial_result["remain_times"]
        join_reach_limit = member_trial_result["join_reach_limit"]
        candidates = [detail for detail in details if not detail.get("has_join")]

        result["member_trial"]["remain_times"] = remain_times
        result["member_trial"]["candidates"] = [
            {
                "title": detail.get("title", ""),
                "session_id": detail.get("session_id", ""),
                "cycle_id": detail.get("cycle_id", ""),
                "has_join": detail.get("has_join", False),
                "stock": detail.get("stock", 0)
            }
            for detail in details
        ]

        if join_reach_limit:
            message = "会员免费试用今日申请次数已达上限"
            result["member_trial"]["message"] = message
            return {
                "success": True,
                "message": message
            }

        if remain_times <= 0:
            message = "会员免费试用无剩余申请次数"
            result["member_trial"]["message"] = message
            return {
                "success": True,
                "message": message
            }

        if not candidates:
            message = "会员免费试用已全部申请，无需重复提交"
            result["member_trial"]["message"] = message
            return {
                "success": True,
                "message": message
            }

        selected_candidates = candidates[:remain_times]
        trial_logger.info(
            "剩余申请次数=%s，本次准备申请=%s 项",
            remain_times,
            len(selected_candidates)
        )

        for index, candidate in enumerate(selected_candidates, start=1):
            if index > 1:
                delay = random.uniform(1, 2)
                trial_logger.info("等待 %.1f 秒后继续申请", delay)
                time.sleep(delay)

            trial_logger.info(
                "正在申请第 %s 项: %s",
                index,
                candidate.get("title", "未知试用")
            )
            sign_up_result = api.sign_up_member_trial(
                portal_info=portal_result,
                component_number=member_trial_result["component_number"],
                component_node_id=member_trial_result["component_node_id"],
                cycle_id=candidate["cycle_id"],
                session_id=candidate["session_id"]
            )

            attempt = {
                "title": candidate.get("title", ""),
                "session_id": candidate.get("session_id", ""),
                "cycle_id": candidate.get("cycle_id", ""),
                "success": sign_up_result["success"],
                "message": sign_up_result.get("reason") or sign_up_result.get("error") or "申请成功"
            }
            result["member_trial"]["attempts"].append(attempt)

            if sign_up_result["success"]:
                trial_logger.info("%s 申请成功", attempt["title"])
            else:
                trial_logger.error("%s 申请失败: %s", attempt["title"], attempt["message"])
                if (
                    sign_up_result.get("error_type") == "token_expired"
                    or self._is_auth_expired_message(attempt["message"])
                ):
                    result["auth_expired"] = True
                    result["member_trial"]["message"] = "Token已过期，请重新登录"
                    return {
                        "success": False,
                        "message": "Token已过期，请重新登录"
                    }

        success_count = sum(1 for attempt in result["member_trial"]["attempts"] if attempt["success"])
        total_attempts = len(result["member_trial"]["attempts"])

        if total_attempts == 0:
            message = "未执行会员免费试用申请"
            success = True
        elif success_count == total_attempts:
            message = f"会员免费试用申请完成，成功 {success_count} 项"
            success = True
        elif success_count > 0:
            message = f"会员免费试用申请部分成功，成功 {success_count}/{total_attempts} 项"
            success = True
        else:
            message = f"会员免费试用申请失败，共尝试 {total_attempts} 项"
            success = False

        result["member_trial"]["message"] = message
        return {
            "success": success,
            "message": message
        }

    def _process_fragment_collect_sign_in(
        self,
        api: DailyBenefitsAPI,
        portal_result: Dict[str, Any],
        page_info: Dict[str, Any],
        account_name: str,
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """处理打卡免费领会员模块"""
        checkin_logger = bind_logger(self.logger, account=account_name, step="打卡签到")
        fragment_result = api.get_fragment_collect_info(page_info)
        if not fragment_result["success"]:
            message = fragment_result["error"]
            result["free_member_checkin"]["message"] = message
            return {
                "success": False,
                "message": message,
                "refresh_page_info": False
            }

        today_record = fragment_result.get("today_record", {})
        result["free_member_checkin"]["sign_date"] = fragment_result["sign_date"]
        result["free_member_checkin"]["sign_status"] = today_record.get("sign_status", "")
        result["free_member_checkin"]["reward_title"] = today_record.get("reward_title", "")

        if fragment_result["is_signed"]:
            message = f"打卡免费领会员今日已签到（{fragment_result['sign_date']}）"
            result["free_member_checkin"]["message"] = message
            return {
                "success": True,
                "message": message,
                "refresh_page_info": False
            }

        checkin_logger.info(
            "开始执行打卡签到，日期=%s",
            fragment_result["sign_date"]
        )
        sign_in_result = api.sign_in_fragment_collect(
            portal_info=portal_result,
            component_number=fragment_result["component_number"],
            component_node_id=fragment_result["component_node_id"],
            sign_date=fragment_result["sign_date"]
        )

        if sign_in_result["success"]:
            reward_title = today_record.get("reward_title", "签到奖励")
            message = f"打卡免费领会员签到成功，奖励: {reward_title}"
            result["free_member_checkin"]["sign_status"] = "signed"
            result["free_member_checkin"]["message"] = message
            return {
                "success": True,
                "message": message,
                "refresh_page_info": True
            }

        message = sign_in_result.get("error", "打卡签到失败")
        if (
            sign_in_result.get("error_type") == "token_expired"
            or self._is_auth_expired_message(message)
        ):
            result["auth_expired"] = True
            message = "Token已过期，请重新登录"
        result["free_member_checkin"]["message"] = message
        return {
            "success": False,
            "message": message,
            "refresh_page_info": False
        }

    def _process_daily_lottery(
        self,
        api: DailyBenefitsAPI,
        portal_result: Dict[str, Any],
        page_info: Dict[str, Any],
        account_name: str,
        result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """处理天天抽奖模块"""
        lottery_logger = bind_logger(self.logger, account=account_name, step="天天抽奖")
        daily_lottery_result = api.get_daily_lottery_info(page_info)
        if not daily_lottery_result["success"]:
            message = daily_lottery_result["error"]
            result["daily_lottery"]["message"] = message
            return {
                "success": False,
                "message": message
            }

        remain_times = daily_lottery_result["remain_times"]
        session_id = daily_lottery_result["session_id"]
        result["daily_lottery"]["remain_times"] = remain_times
        result["daily_lottery"]["session_id"] = session_id
        result["daily_lottery"]["session_name"] = daily_lottery_result.get("session_name", "")
        result["daily_lottery"]["stock_status"] = daily_lottery_result.get("stock_status", "")
        result["daily_lottery"]["reward_pool"] = [
            reward.get("reward_name", "")
            for reward in daily_lottery_result.get("lottery_reward_list", [])
            if reward.get("reward_name")
        ]

        if remain_times <= 0:
            message = "天天抽奖无剩余次数"
            result["daily_lottery"]["message"] = message
            return {
                "success": True,
                "message": message
            }

        lottery_logger.info(
            "剩余抽奖次数=%s，开始执行抽奖",
            remain_times
        )

        for index in range(1, remain_times + 1):
            if index > 1:
                delay = random.uniform(1, 2)
                lottery_logger.info("等待 %.1f 秒后继续抽奖", delay)
                time.sleep(delay)

            lottery_exec_result = api.exec_daily_lottery(
                portal_info=portal_result,
                component_number=daily_lottery_result["component_number"],
                component_node_id=daily_lottery_result["component_node_id"],
                session_id=session_id
            )

            attempt = {
                "index": index,
                "success": lottery_exec_result["success"],
                "reward_name": lottery_exec_result.get("reward_name", ""),
                "reward_type": lottery_exec_result.get("reward_type", ""),
                "message": lottery_exec_result.get("error") or lottery_exec_result.get("reward_name") or "抽奖成功"
            }
            result["daily_lottery"]["attempts"].append(attempt)

            if lottery_exec_result["success"]:
                lottery_logger.info("第 %s 次抽奖成功: %s", index, attempt["reward_name"])
            else:
                lottery_logger.error("第 %s 次抽奖失败: %s", index, attempt["message"])
                if (
                    lottery_exec_result.get("error_type") == "token_expired"
                    or self._is_auth_expired_message(attempt["message"])
                ):
                    result["auth_expired"] = True
                    result["daily_lottery"]["message"] = "Token已过期，请重新登录"
                    return {
                        "success": False,
                        "message": "Token已过期，请重新登录"
                    }
                break

        success_count = sum(1 for attempt in result["daily_lottery"]["attempts"] if attempt["success"])
        total_attempts = len(result["daily_lottery"]["attempts"])

        if total_attempts == 0:
            message = "未执行天天抽奖"
            success = True
        elif success_count == total_attempts:
            message = f"天天抽奖完成，成功 {success_count} 次"
            success = True
        elif success_count > 0:
            message = f"天天抽奖部分成功，成功 {success_count}/{total_attempts} 次"
            success = True
        else:
            message = f"天天抽奖失败，共尝试 {total_attempts} 次"
            success = False

        result["daily_lottery"]["message"] = message
        return {
            "success": success,
            "message": message
        }

    def process_account(self, account_info: Dict[str, Any]) -> Dict[str, Any]:
        """处理单个账号的天天领福利任务"""
        account_name = account_info.get("account_name", "未命名账号")
        account_logger = bind_logger(self.logger, account=account_name)
        log_page_switch(account_logger, self.page_name)

        result = {
            "account_name": account_name,
            "success": False,
            "auth_expired": False,
            "message": "",
            "portal_info": {},
            "free_member_checkin": {
                "sign_date": "",
                "sign_status": "",
                "reward_title": "",
                "message": ""
            },
            "member_trial": {
                "remain_times": 0,
                "candidates": [],
                "attempts": [],
                "message": ""
            },
            "daily_lottery": {
                "remain_times": 0,
                "session_id": "",
                "session_name": "",
                "stock_status": "",
                "reward_pool": [],
                "attempts": [],
                "message": ""
            }
        }

        cookies = account_info.get("cookies", "")
        user_agent = account_info.get("user_agent")
        if not cookies:
            result["message"] = "账号配置中缺少 cookies"
            account_logger.error(result["message"])
            return result

        api = DailyBenefitsAPI(cookies=cookies, user_agent=user_agent)

        portal_result = api.get_benefit_portal()
        if not portal_result["success"]:
            result["message"] = portal_result["error"]
            if (
                portal_result.get("error_type") == "token_expired"
                or self._is_auth_expired_message(result["message"])
            ):
                result["auth_expired"] = True
                result["message"] = "Token已过期，请重新登录"
            log_task_result(account_logger, "📍 入口发现", f"❌ {result['message']}")
            return result

        result["portal_info"] = {
            "title": portal_result.get("title", ""),
            "activity_number": portal_result["activity_number"],
            "page_number": portal_result["page_number"]
        }
        page_info_result = api.get_page_info(portal_result)
        if not page_info_result["success"]:
            result["message"] = page_info_result["error"]
            if (
                page_info_result.get("error_type") == "token_expired"
                or self._is_auth_expired_message(result["message"])
            ):
                result["auth_expired"] = True
                result["message"] = "Token已过期，请重新登录"
            log_task_result(account_logger, "📍 入口发现", f"❌ {result['message']}")
            return result

        current_page_info = page_info_result["data"]
        fragment_collect_status = self._process_fragment_collect_sign_in(
            api=api,
            portal_result=portal_result,
            page_info=current_page_info,
            account_name=account_name,
            result=result
        )

        if fragment_collect_status["refresh_page_info"]:
            refreshed_page_info_result = api.get_page_info(portal_result)
            if refreshed_page_info_result["success"]:
                current_page_info = refreshed_page_info_result["data"]
            else:
                refresh_error = refreshed_page_info_result["error"]
                fragment_collect_status = {
                    "success": False,
                    "message": f"{fragment_collect_status['message']}，但刷新页面信息失败: {refresh_error}"
                }
                result["free_member_checkin"]["message"] = fragment_collect_status["message"]

        if result["auth_expired"]:
            result["success"] = False
            result["message"] = "Token已过期，请重新登录"
            log_task_result(account_logger, "📅 打卡签到", "❌ Token已过期")
            return result

        member_trial_status = self._process_member_trial(
            api=api,
            portal_result=portal_result,
            page_info=current_page_info,
            account_name=account_name,
            result=result
        )
        if result["auth_expired"]:
            result["success"] = False
            result["message"] = "Token已过期，请重新登录"
            log_task_result(account_logger, "🎁 会员试用", "❌ Token已过期")
            return result
        daily_lottery_status = self._process_daily_lottery(
            api=api,
            portal_result=portal_result,
            page_info=current_page_info,
            account_name=account_name,
            result=result
        )
        if result["auth_expired"]:
            result["success"] = False
            result["message"] = "Token已过期，请重新登录"
            log_task_result(account_logger, "🎰 天天抽奖", "❌ Token已过期")
            return result

        result["success"] = (
            fragment_collect_status["success"]
            and member_trial_status["success"]
            and daily_lottery_status["success"]
        )
        result["message"] = " | ".join(
            message
            for message in [
                fragment_collect_status["message"],
                member_trial_status["message"],
                daily_lottery_status["message"]
            ]
            if message
        ) or "处理完成"

        checkin_message = result["free_member_checkin"].get("message", "")
        trial_message = result["member_trial"].get("message", "")
        lottery_message = result["daily_lottery"].get("message", "")

        if checkin_message:
            checkin_status = "✅" if "成功" in checkin_message or "已签到" in checkin_message else "❌"
            if "无" in checkin_message or "已签到" in checkin_message:
                checkin_status = "⏭" if "无" in checkin_message else "✅"
            log_task_result(account_logger, "📅 打卡签到", f"{checkin_status} {checkin_message}")

        if trial_message:
            trial_status = "✅" if "成功" in trial_message else "❌"
            if "无" in trial_message or "已达上限" in trial_message or "无需重复" in trial_message:
                trial_status = "⏭"
            log_task_result(account_logger, "🎁 会员试用", f"{trial_status} {trial_message}")

        if lottery_message:
            lottery_status = "✅" if "成功" in lottery_message else "❌"
            if "无" in lottery_message:
                lottery_status = "⏭"
            log_task_result(account_logger, "🎰 天天抽奖", f"{lottery_status} {lottery_message}")

        return result

    def run(self) -> None:
        """执行所有账号任务"""
        self.logger.info("%s", "=" * 60)
        self.logger.info("WPS 天天领福利任务开始")
        self.logger.info("%s", "=" * 60)

        if not self.accounts:
            self.logger.warning("没有可处理的 WPS 账号")
            return

        for index, account_info in enumerate(self.accounts):
            self.account_results.append(self.process_account(account_info))

            if index < len(self.accounts) - 1:
                delay = random.uniform(3, 8)
                self.logger.info("⏱️  等待 %.1f 秒后处理下一个账号...", delay)
                time.sleep(delay)

        self._print_summary()
        if self.enable_notification:
            self._send_notification()

    @staticmethod
    def build_notification_lines(item: Dict[str, Any]) -> List[str]:
        """构造单账号天天领福利通知内容。"""
        lines = [f"    [{DailyBenefitsTasks.page_name}] {item.get('message', '')}"]

        free_member_checkin = item.get("free_member_checkin", {})
        if free_member_checkin.get("message"):
            lines.append(f"      打卡免费领会员: {free_member_checkin.get('message', '')}")

        member_trial = item.get("member_trial", {})
        lines.append(f"      剩余试用申请次数: {member_trial.get('remain_times', 0)}")
        attempts = member_trial.get("attempts", [])
        if attempts:
            lines.append("      试用申请结果:")
            for attempt in attempts:
                attempt_status = "成功" if attempt["success"] else "失败"
                lines.append(f"        {attempt_status} - {attempt['title']}: {attempt['message']}")

        daily_lottery = item.get("daily_lottery", {})
        lines.append(f"      剩余抽奖次数: {daily_lottery.get('remain_times', 0)}")
        lottery_attempts = daily_lottery.get("attempts", [])
        if lottery_attempts:
            lines.append("      抽奖结果:")
            for attempt in lottery_attempts:
                attempt_status = "成功" if attempt["success"] else "失败"
                lines.append(f"        第{attempt['index']}次 {attempt_status}: {attempt['message']}")

        return lines

    def _print_summary(self) -> None:
        """打印任务统计"""
        self.logger.info("%s", "=" * 60)
        self.logger.info("执行结果统计")
        self.logger.info("%s", "=" * 60)

        total = len(self.account_results)
        success = sum(1 for item in self.account_results if item["success"])
        failed = total - success

        self.logger.info("总账号数: %s", total)
        self.logger.info("执行成功: %s", success)
        self.logger.info("执行失败: %s", failed)

        for item in self.account_results:
            status = "✅ 成功" if item["success"] else "❌ 失败"
            self.logger.info("%s: %s - %s", item["account_name"], status, item["message"])

        self.logger.info("%s", "=" * 60)

    def _send_notification(self) -> None:
        """发送结果通知"""
        if not self.account_results:
            return

        total = len(self.account_results)
        success = sum(1 for item in self.account_results if item["success"])
        failed = total - success

        content_lines = [
            f"📊 总账号数: {total}",
            f"✅ 执行成功: {success}",
            f"❌ 执行失败: {failed}",
            "",
            "📋 详细结果:"
        ]

        for item in self.account_results:
            status = "✅" if item["success"] else "❌"
            content_lines.append(f"{status} {item['account_name']}: {item['message']}")

            portal_info = item.get("portal_info", {})
            if portal_info:
                content_lines.append(
                    f"    🎯 活动页: {portal_info.get('activity_number', '')} / {portal_info.get('page_number', '')}"
                )

            free_member_checkin = item.get("free_member_checkin", {})
            if free_member_checkin.get("message"):
                content_lines.append(f"    📅 打卡免费领会员: {free_member_checkin.get('message', '')}")

            member_trial = item.get("member_trial", {})
            remain_times = member_trial.get("remain_times", 0)
            content_lines.append(f"    🆓 剩余试用申请次数: {remain_times}")

            attempts = member_trial.get("attempts", [])
            if attempts:
                content_lines.append("    📝 申请结果:")
                for attempt in attempts:
                    attempt_status = "成功" if attempt["success"] else "失败"
                    content_lines.append(
                        f"       {attempt_status} - {attempt['title']}: {attempt['message']}"
                    )

            daily_lottery = item.get("daily_lottery", {})
            content_lines.append(f"    🎰 剩余抽奖次数: {daily_lottery.get('remain_times', 0)}")

            lottery_attempts = daily_lottery.get("attempts", [])
            if lottery_attempts:
                content_lines.append("    🎁 抽奖结果:")
                for attempt in lottery_attempts:
                    attempt_status = "成功" if attempt["success"] else "失败"
                    content_lines.append(
                        f"       第{attempt['index']}次 {attempt_status}: {attempt['message']}"
                    )

            if item != self.account_results[-1]:
                content_lines.append("")

        try:
            send_notification(
                title="WPS 天天领福利结果通知",
                content="\n".join(content_lines),
                sound=NotificationSound.BIRDSONG
            )
            self.logger.info("✅ 推送通知已发送")
        except Exception as exc:
            self.logger.warning("⚠️ 发送推送通知失败: %s", exc)


def main() -> None:
    """主函数"""
    try:
        DailyBenefitsTasks().run()
    except FileNotFoundError as exc:
        print(f"❌ 错误: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"❌ 发生未知错误: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
