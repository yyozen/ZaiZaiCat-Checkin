#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
滑动验证码偏移量计算（dachao）

说明：
- 该逻辑从 script/dachao_bak/captcha.py 迁移而来，保持算法一致，供 dachao 阅读任务验证码使用。
- 需要依赖：numpy、Pillow、requests（项目 requirements.txt 通常已包含）。
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Optional

import numpy as np
import requests
from PIL import Image

logger = logging.getLogger(__name__)


def download_captcha_image(url: str) -> Optional[np.ndarray]:
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content))
        if img.mode != "RGB":
            img = img.convert("RGB")
        return np.array(img)
    except Exception as e:
        logger.error(f"下载验证码图片失败: {e}")
        return None


def _calculate_offset_method1(part1_with_gap: np.ndarray, part3_complete: np.ndarray) -> Optional[int]:
    diff = np.abs(part1_with_gap.astype(int) - part3_complete.astype(int))
    diff_gray = np.sum(diff, axis=2) if len(diff.shape) == 3 else diff

    height = diff_gray.shape[0]
    edge_positions = []

    for row in range(height):
        row_diff = diff_gray[row, :]
        threshold = 30
        if np.max(row_diff) > threshold:
            significant = np.where(row_diff > threshold)[0]
            if len(significant) > 0:
                edge_positions.append(significant[0])

    if edge_positions:
        return int(np.median(edge_positions))
    return None


def _calculate_offset_method2(part2_slider: np.ndarray, part3_complete: np.ndarray, slider_width: int = 50) -> int:
    slider = part2_slider[:, 0:slider_width]

    min_diff = float("inf")
    best_x = 0
    img_width = part3_complete.shape[1]

    for x in range(0, img_width - slider_width):
        region = part3_complete[:, x : x + slider_width, :] if len(part3_complete.shape) == 3 else part3_complete[:, x : x + slider_width]
        diff = np.sum((slider.astype(int) - region.astype(int)) ** 2)
        if diff < min_diff:
            min_diff = diff
            best_x = x

    return best_x


def _calculate_offset_method3(part1_with_gap: np.ndarray, part3_complete: np.ndarray) -> Optional[int]:
    diff = np.abs(part1_with_gap.astype(int) - part3_complete.astype(int))
    col_diff = np.sum(diff, axis=(0, 2)) if len(diff.shape) == 3 else np.sum(diff, axis=0)

    threshold = np.mean(col_diff) + 0.8 * np.std(col_diff)
    gap_cols = np.where(col_diff > threshold)[0]

    if len(gap_cols) > 0:
        return int(gap_cols[0])
    return None


def calculate_slide_offset(image_url: str) -> Optional[int]:
    """
    计算滑动验证码的偏移量 tn_x。

    验证码图片由三部分（从上到下）：
    1) 带缺口的背景
    2) 滑块
    3) 完整背景
    """
    img_array = download_captcha_image(image_url)
    if img_array is None:
        return None

    height = img_array.shape[0]
    if height % 3 != 0:
        logger.warning("验证码图片高度不是3的倍数")
        return None

    part_height = height // 3
    part1_with_gap = img_array[0:part_height, :]
    part2_slider = img_array[part_height : part_height * 2, :]
    part3_complete = img_array[part_height * 2 : part_height * 3, :]

    results = []

    try:
        offset1 = _calculate_offset_method1(part1_with_gap, part3_complete)
        if offset1 is not None:
            results.append(offset1)
    except Exception as e:
        logger.debug(f"方法1计算失败: {e}")

    try:
        offset2 = _calculate_offset_method2(part2_slider, part3_complete)
        if offset2 is not None:
            results.append(offset2)
    except Exception as e:
        logger.debug(f"方法2计算失败: {e}")

    try:
        offset3 = _calculate_offset_method3(part1_with_gap, part3_complete)
        if offset3 is not None:
            results.append(offset3)
    except Exception as e:
        logger.debug(f"方法3计算失败: {e}")

    if not results:
        logger.warning("无法检测到缺口位置")
        return None

    final_offset = int(np.median(results))
    logger.info(f"验证码偏移量计算结果: tn_x = {final_offset}")
    return final_offset

