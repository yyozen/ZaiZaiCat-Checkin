#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy API模块

提供WorkBuddy(CodeBuddy CN)签到相关的API接口

接口实现参考 cockpit-tools 项目 (https://github.com/jlcodes99/cockpit-tools)
的 codebuddy_cn_oauth 模块，与官方客户端行为保持一致：
- 签到状态: POST /v2/billing/meter/checkin-activity-status (失败回退 checkin-status)
- 每日签到: POST /v2/billing/meter/daily-checkin
- 刷新令牌: POST /v2/plugin/auth/token/refresh
"""

import logging
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


def _pick_bool(data: Dict[str, Any], snake: str, camel: str, default: bool) -> bool:
    """从响应中宽松读取布尔值，兼容 true/1/'true' 等写法"""
    raw = data.get(snake, data.get(camel))
    if raw is None:
        return default
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return raw != 0
    if isinstance(raw, str):
        lower = raw.strip().lower()
        if lower in ('true', '1'):
            return True
        if lower in ('false', '0'):
            return False
    return default


def _pick_int(data: Dict[str, Any], snake: str, camel: str) -> Optional[int]:
    """从响应中宽松读取整数值，兼容下划线和驼峰命名"""
    raw = data.get(snake, data.get(camel))
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return int(raw)
    if isinstance(raw, str) and raw.strip().lstrip('-').isdigit():
        return int(raw.strip())
    return None


class WorkBuddyAPI:
    """WorkBuddy API类"""

    BASE_URL = 'https://www.codebuddy.cn'
    API_PREFIX = '/v2/plugin'

    # 网关会拒绝缺少浏览器 UA 的请求（403 / code=10085），与 cockpit-tools 保持一致
    DEFAULT_USER_AGENT = (
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
        'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
    )

    # 签到状态接口，按顺序尝试，前者失败时回退到后者
    CHECKIN_STATUS_PATHS = [
        '/v2/billing/meter/checkin-activity-status',
        '/v2/billing/meter/checkin-status',
    ]
    DAILY_CHECKIN_PATH = '/v2/billing/meter/daily-checkin'

    def __init__(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        uid: Optional[str] = None,
        enterprise_id: Optional[str] = None,
        domain: Optional[str] = None,
        user_agent: Optional[str] = None,
        timeout: int = 30,
    ):
        """
        初始化API类

        Args:
            access_token (str): 访问令牌
            refresh_token (Optional[str]): 刷新令牌，用于令牌过期时自动续期
            uid (Optional[str]): 用户ID，对应请求头 X-User-Id
            enterprise_id (Optional[str]): 企业ID，对应请求头 X-Enterprise-Id / X-Tenant-Id
            domain (Optional[str]): 域名，对应请求头 X-Domain
            user_agent (Optional[str]): 用户代理字符串，可选
            timeout (int): 请求超时时间（秒）
        """
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.uid = uid
        self.enterprise_id = enterprise_id
        self.domain = domain
        self.timeout = timeout
        self.user_agent = user_agent or self.DEFAULT_USER_AGENT
        # 令牌被刷新过时置为True，供上层决定是否回写配置文件
        self.token_refreshed = False

    def _build_headers(self) -> Dict[str, str]:
        """
        构造请求头，与官方 buildHeaders(session) 对齐

        Returns:
            Dict[str, str]: 请求头字典
        """
        headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': self.user_agent,
        }

        if self.uid:
            headers['X-User-Id'] = self.uid
        if self.enterprise_id:
            headers['X-Enterprise-Id'] = self.enterprise_id
            headers['X-Tenant-Id'] = self.enterprise_id
        if self.domain:
            headers['X-Domain'] = self.domain

        return headers

    def _post(self, path: str, extra_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        发送POST请求并解析统一响应结构

        Args:
            path (str): 接口路径
            extra_headers (Optional[Dict[str, str]]): 额外请求头

        Returns:
            Dict[str, Any]: 包含success/data/error/error_type的结果字典
        """
        url = f'{self.BASE_URL}{path}'
        headers = self._build_headers()
        if extra_headers:
            headers.update(extra_headers)

        try:
            response = requests.post(url, headers=headers, json={}, timeout=self.timeout)
        except requests.RequestException as e:
            return {'success': False, 'error': f'请求 {path} 失败: {e}', 'error_type': 'network'}

        # 仅 401 视为令牌失效；403 通常是网关拦截（如 UA 校验），保留响应体信息走通用分支
        if response.status_code == 401:
            return {
                'success': False,
                'error': '令牌已失效 (http=401)',
                'error_type': 'token_expired',
            }

        try:
            body = response.json()
        except ValueError:
            return {
                'success': False,
                'error': f'解析 {path} 响应失败: {response.text[:200]}',
                'error_type': 'parse',
            }

        message = body.get('message') or body.get('msg') or 'unknown error'

        if not response.ok:
            return {
                'success': False,
                'error': f'请求 {path} 失败 (http={response.status_code}): {message}',
                'error_type': 'http',
            }

        # 与官方保持一致：仅 code == 0 视为成功
        code = body.get('code', -1)
        if code != 0:
            error_type = 'business'
            if code == 401 or '登录' in str(message) or 'token' in str(message).lower():
                error_type = 'token_expired'
            return {
                'success': False,
                'error': f'{message} (code={code})',
                'error_type': error_type,
                'code': code,
                'body': body,
            }

        if 'data' not in body:
            return {
                'success': False,
                'error': f'{path} 响应缺少 data 字段',
                'error_type': 'parse',
            }

        return {'success': True, 'data': body.get('data') or {}}

    def refresh_access_token(self) -> Dict[str, Any]:
        """
        使用refresh_token换取新的access_token

        Returns:
            Dict[str, Any]: 包含success和新令牌信息的结果字典
        """
        if not self.refresh_token:
            return {'success': False, 'error': '账号未配置 refresh_token，无法自动续期'}

        result = self._post(
            f'{self.API_PREFIX}/auth/token/refresh',
            extra_headers={'X-Refresh-Token': self.refresh_token},
        )

        if not result['success']:
            return {'success': False, 'error': result.get('error', '刷新令牌失败')}

        data = result['data']
        new_access_token = data.get('accessToken') or data.get('access_token')
        if not new_access_token:
            return {'success': False, 'error': '刷新响应中缺少 accessToken'}

        self.access_token = new_access_token
        self.refresh_token = data.get('refreshToken') or data.get('refresh_token') or self.refresh_token
        self.domain = data.get('domain') or self.domain
        self.token_refreshed = True

        expires_at = data.get('expiresAt') or data.get('expires_at')
        logger.info('🔄 访问令牌已刷新')

        return {
            'success': True,
            'access_token': self.access_token,
            'refresh_token': self.refresh_token,
            'expires_at': expires_at,
            'domain': self.domain,
        }

    def _post_with_retry(self, path: str) -> Dict[str, Any]:
        """
        发送POST请求，遇到令牌过期时自动刷新后重试一次

        Args:
            path (str): 接口路径

        Returns:
            Dict[str, Any]: 请求结果字典
        """
        result = self._post(path)

        if result['success'] or result.get('error_type') != 'token_expired':
            return result

        if not self.refresh_token:
            return result

        logger.info('⚠️ 令牌已过期，尝试自动刷新...')
        refresh_result = self.refresh_access_token()
        if not refresh_result['success']:
            return {
                'success': False,
                'error': f"令牌过期且刷新失败: {refresh_result.get('error')}",
                'error_type': 'token_expired',
            }

        return self._post(path)

    def get_checkin_status(self) -> Dict[str, Any]:
        """
        查询今日签到状态

        优先请求 checkin-activity-status（Buddy加油站），失败后回退到 checkin-status

        Returns:
            Dict[str, Any]: 包含签到状态各字段的结果字典
        """
        errors: List[str] = []

        for path in self.CHECKIN_STATUS_PATHS:
            result = self._post_with_retry(path)

            if result['success']:
                return self._parse_checkin_status(result['data'])

            errors.append(result.get('error', '未知错误'))

            # 令牌问题无需继续回退，直接返回
            if result.get('error_type') == 'token_expired':
                return {
                    'success': False,
                    'error': result.get('error'),
                    'error_type': 'token_expired',
                }

        return {
            'success': False,
            'error': '查询签到状态失败: ' + ' | '.join(errors),
            'error_type': 'api',
        }

    @staticmethod
    def _parse_checkin_status(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析签到状态数据，兼容下划线与驼峰两种命名

        Args:
            data (Dict[str, Any]): 接口返回的data字段

        Returns:
            Dict[str, Any]: 标准化后的签到状态
        """
        if not isinstance(data, dict):
            data = {}

        return {
            'success': True,
            # 缺省按已激活处理：有data即认为活动可用，显式false才视为关闭
            'active': _pick_bool(data, 'active', 'Active', True),
            'today_checked_in': _pick_bool(data, 'today_checked_in', 'todayCheckedIn', False),
            'streak_days': _pick_int(data, 'streak_days', 'streakDays') or 0,
            'daily_credit': _pick_int(data, 'daily_credit', 'dailyCredit') or 0,
            'today_credit': _pick_int(data, 'today_credit', 'todayCredit'),
            'next_streak_day': _pick_int(data, 'next_streak_day', 'nextStreakDay'),
            'is_streak_day': _pick_bool(data, 'is_streak_day', 'isStreakDay', False),
            'streak_bonus_days': _pick_int(data, 'streak_bonus_days', 'streakBonusDays'),
            'streak_bonus_credit': _pick_int(data, 'streak_bonus_credit', 'streakBonusCredit'),
            'checkin_dates': data.get('checkin_dates') or data.get('checkinDates') or [],
            'raw': data,
        }

    def daily_checkin(self) -> Dict[str, Any]:
        """
        执行每日签到

        Returns:
            Dict[str, Any]: 包含签到结果、获得积分、连签天数的结果字典
        """
        result = self._post_with_retry(self.DAILY_CHECKIN_PATH)

        if not result['success']:
            # code != 0 属于业务错误（如今日已签到），保留原始信息交由上层判断
            return {
                'success': False,
                'error': result.get('error', '签到失败'),
                'error_type': result.get('error_type', 'api'),
            }

        data = result['data']
        if not isinstance(data, dict):
            data = {}

        # code == 0 时若未显式返回 success 字段，默认视为成功
        success = data.get('success', True)
        credit = _pick_int(data, 'credit', 'today_credit')
        if credit is None:
            credit = _pick_int(data, 'todayCredit', 'credit')

        return {
            'success': bool(success),
            'message': data.get('message') or ('签到成功' if success else '签到失败'),
            'credit': credit,
            'streak_days': _pick_int(data, 'streak_days', 'streakDays'),
            'is_streak_day': _pick_bool(data, 'is_streak_day', 'isStreakDay', False),
            'next_checkin_in': _pick_int(data, 'next_checkin_in', 'nextCheckinIn'),
            'reward': data.get('reward'),
            'raw': data,
        }
