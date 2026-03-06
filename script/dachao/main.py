#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
new Env('大潮App新流程');
cron: 30 10,14,18 * * *
"""

import argparse
import json
import logging
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from notification import NotificationSound, send_notification

from api import (
    NewDachaoAccountConfig,
    TmuyunVappClient,
    discover_news_read_tid,
    login_build_clients,
    run_read_flow,
    run_sign_flow,
    run_sign_lottery_flow,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class AccountResult:
    account_name: str
    sign_ok: bool = False
    sign_msg: str = ""
    sign_lottery_count: int = 0
    sign_lottery_results: List[str] = field(default_factory=list)
    read_total: int = 0
    read_completed: int = 0
    news_lottery_count: int = 0
    news_lottery_results: List[str] = field(default_factory=list)
    error: str = ""


def load_config(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def log_task_header(title: str, timestamp: datetime) -> None:
    logger.info("=" * 60)
    logger.info(f"{title} - {timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)


def _account_section(account_name: str, title: str) -> None:
    logger.info(f"[{account_name}] ===== {title} =====")


def run_account(
    cfg: NewDachaoAccountConfig,
    mode: str,
    *,
    max_articles: int,
    read_delay_min: float,
    read_delay_max: float,
    sleep_enabled: bool,
) -> AccountResult:
    account_name = cfg.account_name
    result = AccountResult(account_name=account_name)

    try:
        logger.info(f"开始处理账号: {account_name}")
        _account_section(account_name, "登录模块")
        _auth_code, ctx, sign_page_url, sign_tid, news_tid, aihoge = login_build_clients(cfg, account_name=account_name)

        if mode in ("all", "sign"):
            _account_section(account_name, "签到模块")
            sign_resp = run_sign_flow(aihoge, sign_tid=sign_tid, sign_page_url=sign_page_url)
            if sign_resp.get("error_code") == 0:
                result.sign_ok = True
                r = sign_resp.get("response") or {}
                days = r.get("continuous_sign_num", 0)
                if r.get("success") == 1:
                    result.sign_msg = f"签到成功，连续签到 {days} 天"
                else:
                    result.sign_msg = f"今日已签到，连续签到 {days} 天"
                logger.info(f"[{account_name}] {result.sign_msg}")
            else:
                result.sign_ok = False
                result.sign_msg = str(sign_resp.get("error_message") or sign_resp)
                logger.warning(f"[{account_name}] 签到失败: {result.sign_msg}")

            time.sleep(random.uniform(2.0, 5.0))

            if cfg.sign_lottery_id:
                _account_section(account_name, "签到抽奖")
                lottery = run_sign_lottery_flow(
                    aihoge,
                    sign_tid=sign_tid,
                    sign_page_url=sign_page_url,
                    sign_lottery_id=cfg.sign_lottery_id,
                )
                result.sign_lottery_count = int(lottery.get("lottery_count") or 0)
                result.sign_lottery_results = list(lottery.get("lottery_results") or [])
                logger.info(f"[{account_name}] 签到抽奖剩余次数: {result.sign_lottery_count}")
                if result.sign_lottery_count <= 0:
                    logger.info(f"[{account_name}] 没有可用的签到抽奖次数")
                else:
                    for prize in result.sign_lottery_results:
                        logger.info(f"[{account_name}] 签到抽奖结果: {prize}")

        if mode in ("all", "read") and news_tid:
            _account_section(account_name, "阅读任务模块")
            vapp = TmuyunVappClient()
            buoy = vapp.buoy_list(ctx, user_agent=cfg.user_agent, cookies=cfg.vapp_cookies)
            news_entry_url, _ = discover_news_read_tid(buoy)

            delay_min = float(read_delay_min)
            delay_max = float(read_delay_max)
            if delay_min > delay_max:
                delay_min, delay_max = delay_max, delay_min

            read_stats = run_read_flow(
                aihoge=aihoge,
                vapp=vapp,
                ctx=ctx,
                news_tid=news_tid,
                news_entry_url=news_entry_url,
                vapp_user_agent=cfg.user_agent,
                vapp_cookies=cfg.vapp_cookies,
                read_delay_range_s=(max(0.0, delay_min), max(0.0, delay_max)),
                sleep_enabled=bool(sleep_enabled),
                account_name=account_name,
            )
            result.read_total = int(read_stats.get("total") or 0)
            result.read_completed = int(read_stats.get("completed") or 0)
            result.news_lottery_count = int(read_stats.get("lottery_count") or 0)
            result.news_lottery_results = list(read_stats.get("lottery_results") or [])

            logger.info(f"[{account_name}] 阅读抽奖剩余次数: {result.news_lottery_count}")
            if result.news_lottery_count <= 0:
                logger.info(f"[{account_name}] 没有可用的阅读抽奖次数")
            else:
                for prize in result.news_lottery_results:
                    logger.info(f"[{account_name}] 阅读抽奖结果: {prize}")

        return result

    except Exception as e:
        result.error = str(e)
        logger.error(f"处理账号 {account_name} 时发生错误: {e}")
        return result


def _send_summary_notification(results: List[AccountResult], start_time: datetime, end_time: datetime, mode: str) -> None:
    duration = (end_time - start_time).total_seconds()

    total_accounts = len(results)
    success_accounts = sum(1 for r in results if not r.error)
    total_sign_success = sum(1 for r in results if r.sign_ok)
    total_sign_lottery = sum(r.sign_lottery_count for r in results)
    total_read_completed = sum(r.read_completed for r in results)
    total_news_lottery = sum(r.news_lottery_count for r in results)

    title = "大潮App新流程任务完成 ✅"

    content_parts = [
        "📊 总体统计",
        "━━━━━━━━━━━━━━━━",
        f"👥 账号数量: {total_accounts}个",
        f"✅ 成功账号: {success_accounts}/{total_accounts}",
    ]

    if mode in ("all", "sign"):
        content_parts.extend(
            [
                f"📝 签到成功: {total_sign_success}/{total_accounts}",
                f"🎰 签到抽奖: {total_sign_lottery}次",
            ]
        )
    if mode in ("all", "read"):
        content_parts.extend(
            [
                f"📖 完成阅读: {total_read_completed}篇",
                f"🎰 阅读抽奖: {total_news_lottery}次",
            ]
        )

    content_parts.extend([f"⏱️ 执行耗时: {int(duration)}秒", "", "📋 账号详情", "━━━━━━━━━━━━━━━━"])

    for idx, r in enumerate(results, 1):
        if r.error:
            content_parts.append(f"❌ [{r.account_name}] 执行失败")
            content_parts.append(f"   错误: {r.error}")
        else:
            sign_status = "✅" if r.sign_ok else "❌"
            content_parts.append(f"{sign_status} [{r.account_name}]")
            if mode in ("all", "sign"):
                content_parts.append(f"   📝 签到: {r.sign_msg or ('成功' if r.sign_ok else '失败')}")
                content_parts.append(f"   🎰 签到抽奖: {r.sign_lottery_count}次")
                if r.sign_lottery_results:
                    content_parts.append("   🎁 签到奖励:")
                    for prize in r.sign_lottery_results:
                        content_parts.append(f"      - {prize}")
            if mode in ("all", "read"):
                content_parts.append(f"   📖 阅读任务: {r.read_completed}/{r.read_total}")
                content_parts.append(f"   🎰 阅读抽奖: {r.news_lottery_count}次")
                if r.news_lottery_results:
                    content_parts.append("   🎁 阅读奖励:")
                    for prize in r.news_lottery_results:
                        content_parts.append(f"      - {prize}")

        if idx < len(results):
            content_parts.append("")

    content_parts.append("━━━━━━━━━━━━━━━━")
    content_parts.append(f"🕐 {end_time.strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        send_notification(title=title, content="\n".join(content_parts), sound=NotificationSound.BIRDSONG)
        logger.info("✅ 大潮App新流程任务汇总推送发送成功")
    except Exception as e:
        logger.error(f"❌ 发送任务汇总推送失败: {str(e)}", exc_info=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(project_root / "config" / "token.json"))
    parser.add_argument("--mode", choices=["all", "sign", "read"], default="all")
    parser.add_argument("--max-articles", type=int, default=6)
    parser.add_argument("--read-delay-min", type=float, default=20.0)
    parser.add_argument("--read-delay-max", type=float, default=30.0)
    # 调试参数：
    # - --no-sleep：跳过真实阅读等待（但仍会用最小 read_time 上报），用于快速验证流程
    # - --fast：快捷组合参数，方便在 IDE 调试时快速跑通
    parser.add_argument("--no-sleep", action="store_true", help="不等待直接上报阅读时间（调试用）")
    parser.add_argument("--fast", action="store_true", help="调试快捷模式（等同于 --max-articles 2 --read-delay-min 1 --read-delay-max 2）")
    args = parser.parse_args()

    start_time = datetime.now()
    log_task_header("大潮App新流程开始执行", start_time)

    try:
        cfg_path = Path(args.config)
        logger.info(f"正在读取配置文件: {cfg_path}")
        raw = load_config(cfg_path).get("dachao", {})
        accounts_raw = raw.get("accounts", [])
        debug = bool(raw.get("debug") or False)
        if debug:
            logging.getLogger().setLevel(logging.DEBUG)
            # 我们会在 api.py 里输出结构化 HTTP 调试信息；
            # urllib3 自带的 connectionpool DEBUG 会非常吵，调试时建议压制为 WARNING。
            logging.getLogger("urllib3").setLevel(logging.WARNING)

        accounts: List[NewDachaoAccountConfig] = []
        for a in accounts_raw:
            try:
                accounts.append(NewDachaoAccountConfig.from_dict(a))
            except Exception as e:
                logger.error(f"账号配置异常: {e}")

        if not accounts:
            logger.warning("配置文件中没有找到大潮账号信息")
            return 2

        logger.info(f"成功加载 {len(accounts)} 个账号配置")

        if args.fast:
            args.max_articles = 2
            args.read_delay_min = 1.0
            args.read_delay_max = 2.0

        logger.info(f"开始执行任务，共 {len(accounts)} 个账号")

        results: List[AccountResult] = []
        for i, acc in enumerate(accounts, 1):
            logger.info(f"\n{'=' * 60}")
            logger.info(f"处理第 {i}/{len(accounts)} 个账号")
            logger.info(f"{'=' * 60}")

            results.append(
                run_account(
                    acc,
                    mode=args.mode,
                    max_articles=args.max_articles,
                    read_delay_min=args.read_delay_min,
                    read_delay_max=args.read_delay_max,
                    sleep_enabled=(not args.no_sleep),
                )
            )
            logger.info(f"账号 {i} 处理完成")

            if i < len(accounts):
                account_delay = random.uniform(3.0, 8.0)
                logger.info(f"账号切换延时 {account_delay:.2f} 秒...")
                time.sleep(account_delay)

        logger.info("所有账号任务处理完成")

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.info("=" * 60)
        logger.info(f"大潮App新流程执行完成 - {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"执行耗时: {int(duration)} 秒")
        logger.info("=" * 60)

        _send_summary_notification(results, start_time, end_time, mode=args.mode)
        return 0 if all(not r.error for r in results) else 1

    except Exception as e:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.error(f"任务执行异常: {str(e)}", exc_info=True)

        try:
            send_notification(
                title="大潮App新流程任务异常 ❌",
                content=(
                    f"❌ 任务执行异常\n"
                    f"💬 错误信息: {str(e)}\n"
                    f"⏱️ 执行耗时: {int(duration)}秒\n"
                    f"🕐 完成时间: {end_time.strftime('%Y-%m-%d %H:%M:%S')}"
                ),
                sound=NotificationSound.ALARM,
            )
        except Exception:
            logger.error("发送异常通知失败", exc_info=True)

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
