#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new Env('WPS任务中心');
cron: 1 1 1 1 1
"""

"""
WPS 任务中心活动脚本

该脚本将 main.py 中当前的核心业务流程独立为单独活动页面，包括：
- 读取账号配置信息
- 执行任务中心签到
- 获取任务中心用户信息
- 执行任务中心抽奖
- 推送执行结果

Author: Assistant
Date: 2026-03-11
"""

import json
import logging
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from api import WPSAPI
from logging_utils import (
    bind_logger,
    configure_logging,
    get_logger,
    log_page_switch,
    log_task_result,
)

# 获取项目根目录
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from notification import send_notification, NotificationSound


class WPSTaskCenterPage:
    """WPS 任务中心活动执行器"""

    page_name = "任务中心"

    def __init__(self, config_path: str = None, enable_notification: bool = True, load_accounts: bool = True):
        if config_path is None:
            self.config_path = project_root / "config" / "token.json"
        else:
            self.config_path = Path(config_path)

        self.enable_notification = enable_notification
        self.accounts: List[Dict[str, Any]] = []
        self.account_results: List[Dict[str, Any]] = []
        self.logger = self._setup_logger()
        if load_accounts:
            self._init_accounts()

    def _setup_logger(self) -> logging.Logger:
        configure_logging()
        return bind_logger(get_logger("task_center"), page=self.page_name)

    def _init_accounts(self) -> None:
        """从配置文件中读取 WPS 账号信息"""
        if not self.config_path.exists():
            self.logger.error("配置文件不存在: %s", self.config_path)
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")

        try:
            with open(self.config_path, "r", encoding="utf-8") as file:
                config_data = json.load(file)
        except json.JSONDecodeError as exc:
            self.logger.error("配置文件 JSON 解析失败: %s", exc)
            raise
        except Exception as exc:
            self.logger.error("读取配置文件失败: %s", exc)
            raise

        wps_config = config_data.get("wps", {})
        self.accounts = wps_config.get("accounts", [])

        if self.accounts:
            self.logger.info("成功加载 %s 个账号配置", len(self.accounts))
        else:
            self.logger.warning("配置文件中没有找到 wps 账号信息")

    @staticmethod
    def _is_auth_expired_message(message: str) -> bool:
        keywords = ("Token已过期", "ErrNotLogin", "userNotLogin", "未登录", "请重新登录")
        return any(keyword in str(message) for keyword in keywords)

    def process_account(self, account_info: Dict[str, Any]) -> Dict[str, Any]:
        """处理单个账号的任务中心任务"""
        account_name = account_info.get("account_name", "未命名账号")
        account_logger = bind_logger(self.logger, account=account_name)
        log_page_switch(account_logger, self.page_name)

        result = {
            "account_name": account_name,
            "success": False,
            "auth_expired": False,
            "message": "",
            "sign_info": {},
            "sign_rewards": [],
            "lottery_info": {},
            "user_info": {},
            "final_user_info": {}
        }

        try:
            user_id = account_info.get("user_id")
            cookies = account_info.get("cookies", "")
            user_agent = account_info.get("user_agent")

            if not user_id:
                result["message"] = "账号配置中缺少 user_id，跳过任务中心签到"
                account_logger.warning(result["message"])
                return result

            if not cookies:
                result["message"] = "账号配置中缺少 cookies"
                account_logger.error(result["message"])
                return result

            api = WPSAPI(cookies=cookies, user_agent=user_agent)

            sign_result = api.sign_in(user_id=user_id)
            if not sign_result["success"]:
                error_type = sign_result.get("error_type", "")
                error_msg = sign_result.get("error", "任务中心签到失败")
                if error_type == "token_expired":
                    result["auth_expired"] = True
                    result["message"] = "Token已过期，请重新登录"
                    log_task_result(account_logger, "🔐 签到", "❌ Token已过期")
                else:
                    result["message"] = error_msg
                    log_task_result(account_logger, "🔐 签到", f"❌ {error_msg}")
                return result

            result["success"] = True
            result["sign_info"] = sign_result.get("data", {}) or {}
            if sign_result.get("already_signed"):
                result["message"] = "任务中心今日已签到"
                log_task_result(account_logger, "🔐 签到", "✅ 今日已签到")
            else:
                result["message"] = "任务中心签到成功"
                log_task_result(account_logger, "🔐 签到", "✅ 签到成功")

                rewards = result["sign_info"].get("rewards", [])
                reward_names = [
                    reward.get("reward_name", "")
                    for reward in rewards
                    if reward.get("reward_name")
                ]
                result["sign_rewards"] = reward_names

            user_info_result = api.get_user_info()
            if user_info_result["success"]:
                result["user_info"] = user_info_result
            else:
                if (
                    user_info_result.get("error_type") == "token_expired"
                    or self._is_auth_expired_message(user_info_result.get("error", ""))
                ):
                    result["auth_expired"] = True
                    result["message"] = "Token已过期，请重新登录"
                    result["success"] = False
                    log_task_result(account_logger, "💎 积分", "❌ Token已过期")
                    return result
                log_task_result(
                    account_logger,
                    "💎 积分",
                    f"⚠ 获取失败: {user_info_result.get('error', '获取用户信息失败')}"
                )

            lottery_times = result["user_info"].get("lottery_times", 0)
            component_number = result["user_info"].get("lottery_component_number", "ZJ2025092916515917")
            component_node_id = result["user_info"].get("lottery_component_node_id", "FN1762346087mJlk")

            default_max_lottery = 5
            max_lottery_limit = account_info.get("max_lottery_limit")
            if max_lottery_limit is None:
                max_lottery_limit = default_max_lottery
                is_custom_limit = False
            else:
                is_custom_limit = True

            actual_lottery_times = min(lottery_times, max_lottery_limit)
            if lottery_times > 0:
                lottery_results = []
                prize_list = []

                for index in range(actual_lottery_times):
                    delay = random.uniform(1, 3)
                    time.sleep(delay)

                    lottery_result = api.lottery(
                        component_number=component_number,
                        component_node_id=component_node_id
                    )
                    lottery_results.append(lottery_result)

                    if lottery_result["success"]:
                        prize_name = lottery_result.get("prize_name", "未知奖品")
                        prize_list.append(prize_name)
                    else:
                        error_type = lottery_result.get("error_type", "")
                        error_msg = lottery_result.get("error", "任务中心抽奖失败")
                        if error_type == "token_expired" or self._is_auth_expired_message(error_msg):
                            result["auth_expired"] = True
                            result["message"] = "Token已过期，请重新登录"
                            result["success"] = False
                            result["lottery_info"] = {
                                "total_attempts": len(lottery_results),
                                "successful_draws": len([item for item in lottery_results if item["success"]]),
                                "results": lottery_results,
                                "prizes": prize_list
                            }
                            log_task_result(account_logger, "🎰 抽奖", "❌ Token已过期")
                            return result
                        log_task_result(account_logger, "🎰 抽奖", f"❌ {error_msg}")

                result["lottery_info"] = {
                    "total_attempts": actual_lottery_times,
                    "successful_draws": len([item for item in lottery_results if item["success"]]),
                    "results": lottery_results,
                    "prizes": prize_list
                }

                if prize_list:
                    log_task_result(account_logger, "🎰 抽奖", f"✅ {', '.join(prize_list)}")
                else:
                    log_task_result(account_logger, "🎰 抽奖", "⚠ 未中奖")
            else:
                log_task_result(account_logger, "🎰 抽奖", "⏭ 无可用次数")

            final_user_info = api.get_user_info()
            if final_user_info["success"]:
                result["final_user_info"] = final_user_info
                log_task_result(account_logger, "💎 积分", f"{final_user_info.get('points', 0)} pt")
            else:
                if (
                    final_user_info.get("error_type") == "token_expired"
                    or self._is_auth_expired_message(final_user_info.get("error", ""))
                ):
                    result["auth_expired"] = True
                    result["message"] = "Token已过期，请重新登录"
                    result["success"] = False
                    log_task_result(account_logger, "💎 积分", "❌ Token已过期")
                    return result
                log_task_result(account_logger, "💎 积分", "⚠ 获取失败")

        except Exception as exc:
            result["success"] = False
            result["message"] = f"处理任务中心账号时发生异常: {exc}"
            account_logger.error(result["message"])
            import traceback
            traceback.print_exc()

        return result

    @staticmethod
    def build_notification_lines(result: Dict[str, Any]) -> List[str]:
        """构造单账号任务中心通知内容。"""
        lines = [f"    [{WPSTaskCenterPage.page_name}] {result.get('message', '')}"]

        sign_rewards = result.get("sign_rewards", [])
        if sign_rewards:
            lines.append(f"      签到奖励: {', '.join(sign_rewards)}")

        lottery_info = result.get("lottery_info", {})
        lottery_results = lottery_info.get("results", [])
        if lottery_results:
            lines.append("      抽奖结果:")
            for index, single_result in enumerate(lottery_results, start=1):
                if single_result["success"]:
                    prize_name = single_result.get("prize_name", "未知")
                    lines.append(f"        第{index}次: {prize_name}")
                else:
                    error_msg = single_result.get("error", "抽奖失败")
                    lines.append(f"        第{index}次: {error_msg}")

        final_info = result.get("final_user_info", {}) or {}
        if final_info.get("success"):
            lines.append(
                f"      账户信息: 抽奖次数 {final_info.get('lottery_times', 0)} | "
                f"积分 {final_info.get('points', 0)} | 即将过期 {final_info.get('advent_points', 0)}"
            )

        return lines

    def run(self) -> None:
        """执行所有任务中心账号任务"""
        self.logger.info("%s", "=" * 60)
        self.logger.info("WPS任务中心任务开始")
        self.logger.info("%s", "=" * 60)

        if not self.accounts:
            self.logger.warning("没有需要处理的账号")
            return

        for index, account_info in enumerate(self.accounts):
            self.account_results.append(self.process_account(account_info))
            if index < len(self.accounts) - 1:
                delay = random.uniform(5, 10)
                self.logger.info("等待 %.1f 秒后处理下一个账号...", delay)
                time.sleep(delay)

        self._print_summary()
        if self.enable_notification:
            self._send_notification()

    def _print_summary(self) -> None:
        """打印任务中心执行结果统计"""
        self.logger.info("%s", "=" * 60)
        self.logger.info("任务中心执行结果统计")
        self.logger.info("%s", "=" * 60)

        total = len(self.account_results)
        success = sum(1 for item in self.account_results if item["success"])
        failed = total - success

        self.logger.info("总账号数: %s", total)
        self.logger.info("执行成功: %s", success)
        self.logger.info("执行失败: %s", failed)

        prize_summary: Dict[str, int] = {}
        total_attempts = 0
        total_successful_draws = 0

        for result in self.account_results:
            lottery_info = result.get("lottery_info")
            if not lottery_info:
                continue

            lottery_results = lottery_info.get("results", [])
            for single_result in lottery_results:
                if not single_result["success"]:
                    continue

                lottery_data = single_result.get("data", {})
                prize_name = lottery_data.get("prize_name", "未知")
                if prize_name and prize_name not in {"未知", "未中奖"}:
                    prize_summary[prize_name] = prize_summary.get(prize_name, 0) + 1

            total_attempts += lottery_info.get("total_attempts", 0)
            total_successful_draws += lottery_info.get("successful_draws", 0)

        if total_attempts > 0:
            self.logger.info("📊 抽奖统计: 总共尝试 %s 次，成功 %s 次", total_attempts, total_successful_draws)

        if prize_summary:
            self.logger.info("🎁 任务中心奖品统计:")
            for prize, count in prize_summary.items():
                self.logger.info("  %s: %s 个", prize, count)

        self.logger.info("详细结果:")
        for result in self.account_results:
            status = "✅ 成功" if result["success"] else "❌ 失败"
            self.logger.info("  %s: %s - %s", result["account_name"], status, result["message"])

        self.logger.info("%s", "=" * 60)

    def _send_notification(self) -> None:
        """发送任务中心结果通知"""
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

        for result in self.account_results:
            status = "✅" if result["success"] else "❌"
            content_lines.append(f"{status} {result['account_name']}: {result['message']}")

            sign_rewards = result.get("sign_rewards", [])
            if sign_rewards:
                content_lines.append(f"    🎁 签到奖励: {', '.join(sign_rewards)}")

            lottery_info = result.get("lottery_info", {})
            lottery_results = lottery_info.get("results", [])
            if lottery_results:
                content_lines.append("    🎲 抽奖结果:")
                for index, single_result in enumerate(lottery_results, start=1):
                    if single_result["success"]:
                        prize_name = single_result.get("prize_name", "未知")
                        content_lines.append(f"       第{index}次: {prize_name}")
                    else:
                        error_msg = single_result.get("error", "抽奖失败")
                        content_lines.append(f"       第{index}次: {error_msg}")

            final_info = result.get("final_user_info", {}) or {}
            if final_info.get("success"):
                content_lines.append(
                    f"    📊 账户信息: 抽奖次数 {final_info.get('lottery_times', 0)} | "
                    f"积分 {final_info.get('points', 0)} | 即将过期 {final_info.get('advent_points', 0)}"
                )
            else:
                content_lines.append("    ⚠️ 账户信息获取失败")

            if result != self.account_results[-1]:
                content_lines.append("")

        try:
            send_notification(
                title="WPS任务中心结果通知",
                content="\n".join(content_lines),
                sound=NotificationSound.BIRDSONG
            )
            self.logger.info("✅ 任务中心推送通知已发送")
        except Exception as exc:
            self.logger.warning("⚠️ 发送任务中心推送通知失败: %s", exc)


def main() -> None:
    """主函数"""
    try:
        WPSTaskCenterPage().run()
    except FileNotFoundError as exc:
        print(f"❌ 错误: {exc}")
        print("请确保配置文件存在并包含 WPS 账号信息")
        sys.exit(1)
    except Exception as exc:
        print(f"❌ 发生未知错误: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
