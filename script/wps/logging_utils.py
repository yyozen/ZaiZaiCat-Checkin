#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WPS 脚本统一日志配置。"""

import logging
from typing import Any, Mapping, MutableMapping, Optional


LOG_FORMAT = "%(asctime)s | %(levelname)-5s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class ContextAdapter(logging.LoggerAdapter):
    """支持层层叠加上下文的日志适配器。"""

    def process(self, msg: str, kwargs: MutableMapping[str, Any]) -> tuple[str, MutableMapping[str, Any]]:
        extra: Mapping[str, Any] = kwargs.get("extra", {})
        merged_extra = dict(self.extra)
        merged_extra.update(extra)
        kwargs["extra"] = merged_extra
        return msg, kwargs


def configure_logging(level: int = logging.INFO) -> None:
    """集中配置根日志，重复调用安全。"""
    root_logger = logging.getLogger()
    formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    if root_logger.handlers:
        for handler in root_logger.handlers:
            handler.setLevel(level)
            handler.setFormatter(formatter)
    else:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    root_logger.setLevel(level)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """获取统一命名空间下的日志器。"""
    if not name:
        return logging.getLogger("wps")
    return logging.getLogger(f"wps.{name}")


def bind_logger(logger: logging.Logger | ContextAdapter, **context: Any) -> ContextAdapter:
    """为日志器绑定上下文。"""
    if isinstance(logger, ContextAdapter):
        merged_context = dict(logger.extra)
        merged_context.update(context)
        return ContextAdapter(logger.logger, merged_context)
    return ContextAdapter(logger, context)


def log_divider(logger: logging.Logger | ContextAdapter, title: str = "") -> None:
    """输出轻量分隔线，便于扫描日志阶段。"""
    if title:
        logger.info("---- %s ----", title)
    else:
        logger.info("--------------------")


def log_banner(logger: logging.Logger | ContextAdapter, title: str) -> None:
    """输出较明显的标题分隔。"""
    line = "═" * 38
    logger.info(line)
    logger.info(title)
    logger.info(line)


def log_account_start(logger: logging.Logger | ContextAdapter, account_name: str) -> None:
    """输出账号开始日志。"""
    line = "━" * 32
    logger.info(line)
    logger.info("👤 账号：%s", account_name)
    logger.info(line)


def log_account_end(
    logger: logging.Logger | ContextAdapter,
    account_name: str,
    success: bool = True,
    wait_seconds: Optional[float] = None
) -> None:
    """输出账号结束日志。"""
    icon = "✅" if success else "❌"
    if wait_seconds is not None:
        logger.info("%s %s 完成，等待 %.1fs", icon, account_name, wait_seconds)
        return
    logger.info("%s %s 完成", icon, account_name)


def log_page_switch(logger: logging.Logger | ContextAdapter, page_name: str) -> None:
    """输出页面切换日志。"""
    logger.info("📄 页面：%s", page_name)


def log_step_start(logger: logging.Logger | ContextAdapter, step_name: str) -> None:
    """输出步骤开始日志。"""
    logger.info("  ┌─ [%s] 开始执行", step_name)


def log_step_line(logger: logging.Logger | ContextAdapter, message: str, *args: Any) -> None:
    """输出步骤中的过程日志。"""
    logger.info(f"  │  {message}", *args)


def log_step_end(
    logger: logging.Logger | ContextAdapter,
    message: str,
    *,
    status: str = "success"
) -> None:
    """输出步骤结束日志。"""
    icon_map = {
        "success": "✅",
        "warn": "⚠",
        "error": "❌",
        "info": "ℹ",
    }
    logger.info("  └─ %s %s", icon_map.get(status, "•"), message)


def log_startup(logger: logging.Logger | ContextAdapter, total_accounts: int) -> None:
    """输出启动摘要。"""
    logger.info("📦 WPS 任务启动，共 %s 个账号", total_accounts)


def log_task_result(logger: logging.Logger | ContextAdapter, label: str, result: str) -> None:
    """输出简洁任务结果行。"""
    logger.info("  %-10s → %s", label, result)
