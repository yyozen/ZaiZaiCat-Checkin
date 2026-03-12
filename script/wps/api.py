#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WPS API模块

提供WPS签到相关的API接口和加密功能
"""

import base64
import time
import random
import string
import requests
import json
import logging
from typing import Dict, Optional
from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad

logger = logging.getLogger(__name__)
logger.setLevel(logging.WARNING)


class WPSEncryption:
    """WPS加密工具类"""

    @staticmethod
    def generate_aes_key(length: int = 32) -> str:
        """
        生成AES密钥: 随机字符 + 时间戳

        Args:
            length (int): 密钥长度，默认32位

        Returns:
            str: 生成的AES密钥
        """
        chars = string.ascii_lowercase + string.digits
        random_part = ''.join(random.choice(chars) for _ in range(length - 10))
        timestamp_part = str(int(time.time()))
        return random_part + timestamp_part

    @staticmethod
    def aes_encrypt(plain_text: str, aes_key: str) -> str:
        """
        AES-CBC加密

        Args:
            plain_text (str): 明文文本
            aes_key (str): AES密钥

        Returns:
            str: Base64编码的加密结果
        """
        # 将密钥转为bytes并零填充到32字节
        key_bytes = aes_key.encode('utf-8')
        key_padded = key_bytes + b'\x00' * (32 - len(key_bytes))

        # 使用前16位作为IV
        iv = aes_key[:16].encode('utf-8')

        # 创建AES加密器 (CBC模式)
        cipher = AES.new(key_padded, AES.MODE_CBC, iv)

        # PKCS7填充
        plain_bytes = plain_text.encode('utf-8')
        padded_data = pad(plain_bytes, AES.block_size)

        # 加密并返回Base64
        encrypted = cipher.encrypt(padded_data)
        return base64.b64encode(encrypted).decode('utf-8')

    @staticmethod
    def rsa_encrypt(plain_text: str, public_key_pem: str) -> str:
        """
        RSA加密

        Args:
            plain_text (str): 明文文本
            public_key_pem (str): PEM格式的RSA公钥

        Returns:
            str: Base64编码的加密结果
        """
        public_key = RSA.import_key(public_key_pem)
        cipher = PKCS1_v1_5.new(public_key)
        encrypted = cipher.encrypt(plain_text.encode('utf-8'))
        return base64.b64encode(encrypted).decode('utf-8')


class WPSAPI:
    """WPS API类"""

    def __init__(self, cookies: str, user_agent: Optional[str] = None):
        """
        初始化API类

        Args:
            cookies (str): Cookie字符串
            user_agent (Optional[str]): 用户代理字符串，可选
        """
        self.cookies = self._parse_cookies(cookies)
        self.user_agent = user_agent or (
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
            'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36'
        )
        self.base_headers = {
            'User-Agent': self.user_agent,
            'Accept': 'application/json, text/plain, */*',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Content-Type': 'application/json',
            'pragma': 'no-cache',
            'cache-control': 'no-cache',
            'sec-ch-ua-platform': '"macOS"',
            'sec-ch-ua': '"Chromium";v="142", "Brave";v="142", "Not_A Brand";v="99"',
            'sec-ch-ua-mobile': '?0',
            'sec-gpc': '1',
            'accept-language': 'zh-CN,zh;q=0.9',
            'origin': 'https://personal-act.wps.cn',
            'sec-fetch-site': 'same-site',
            'sec-fetch-mode': 'cors',
            'sec-fetch-dest': 'empty',
            'referer': 'https://personal-act.wps.cn/',
            'priority': 'u=1, i'
        }
        self.encrypt_key_url = 'https://personal-bus.wps.cn/sign_in/v1/encrypt/key'
        self.sign_in_url = 'https://personal-bus.wps.cn/sign_in/v1/sign_in'
        self.lottery_url = 'https://personal-act.wps.cn/activity-rubik/activity/component_action'
        self.user_info_url = 'https://personal-act.wps.cn/activity-rubik/activity/page_info'
        self.encryption = WPSEncryption()

    @staticmethod
    def _parse_cookies(cookie_str: str) -> Dict[str, str]:
        """
        解析Cookie字符串为字典

        Args:
            cookie_str (str): Cookie字符串

        Returns:
            Dict[str, str]: Cookie字典
        """
        cookies = {}
        for item in cookie_str.split('; '):
            if '=' in item:
                key, value = item.split('=', 1)
                cookies[key] = value
        return cookies

    def get_user_info(self, activity_number: str = "HD2025031821201822",
                      page_number: str = "YM2025041617143388") -> Dict:
        """
        获取用户个人信息，包括抽奖次数和积分

        Args:
            activity_number (str): 活动编号
            page_number (str): 页面编号

        Returns:
            Dict: 用户信息结果
                {
                    'success': bool,           # 是否成功
                    'lottery_times': int,      # 抽奖次数
                    'points': int,             # 当前积分
                    'advent_points': int,      # 即将过期积分
                    'lottery_component_number': str,  # 抽奖组件编号
                    'lottery_component_node_id': str, # 抽奖组件节点ID
                    'points_component_number': str,   # 积分组件编号
                    'points_component_node_id': str,  # 积分组件节点ID
                    'raw_data': dict,          # 原始返回数据
                    'error': str               # 失败时的错误信息
                }
        """
        logger.info("正在获取用户个人信息...")

        try:
            # 构造请求头
            headers = self.base_headers.copy()
            headers['referer'] = f'https://personal-act.wps.cn/rubik2/portal/{activity_number}/{page_number}?cs_from=&mk_key=JkVKsOtv4aCLMdNdAKwUGoz9tfKeFZVKyjEe&position=mac_grzx_sign'
            headers['sec-fetch-site'] = 'same-origin'
            headers['sec-fetch-mode'] = 'cors'
            headers['sec-fetch-dest'] = 'empty'

            # 构造请求参数
            params = {
                'activity_number': activity_number,
                'page_number': page_number
            }

            # 发送GET请求
            response = requests.get(
                self.user_info_url,
                headers=headers,
                cookies=self.cookies,
                params=params,
                timeout=30
            )

            logger.debug(f"用户信息请求URL: {response.url}")
            logger.debug(f"用户信息响应状态码: {response.status_code}")
            logger.debug(f"用户信息响应内容: {response.text}")

            response.raise_for_status()
            result = response.json()

            if result.get('result') == 'ok' and 'data' in result:
                data_list = result.get('data', [])

                # 初始化返回结果
                user_info = {
                    'success': True,
                    'lottery_times': 0,
                    'points': 0,
                    'advent_points': 0,
                    'lottery_component_number': '',
                    'lottery_component_node_id': '',
                    'points_component_number': '',
                    'points_component_node_id': '',
                    'raw_data': result
                }

                # 遍历data列表查找抽奖和积分信息
                for item in data_list:
                    item_type = item.get('type')

                    # type 45 是抽奖信息
                    if item_type == 45 and 'lottery_v2' in item:
                        lottery_v2 = item.get('lottery_v2', {})
                        lottery_list = lottery_v2.get('lottery_list', [])

                        # 查找进行中的抽奖会话
                        for lottery_session in lottery_list:
                            if lottery_session.get('session_status') == 'IN_PROGRESS':
                                user_info['lottery_times'] = lottery_session.get('times', 0)
                                user_info['lottery_component_number'] = item.get('number', '')
                                user_info['lottery_component_node_id'] = item.get('component_node_id', '')
                                logger.info(f"✅ 获取到抽奖信息: 剩余次数 {user_info['lottery_times']} 次")
                                break

                    # type 36 是积分信息
                    elif item_type == 36 and 'task_center_user_info' in item:
                        task_center = item.get('task_center_user_info', {})
                        user_info['points'] = task_center.get('integral', 0)
                        user_info['advent_points'] = task_center.get('advent_integral', 0)
                        user_info['points_component_number'] = item.get('number', '')
                        user_info['points_component_node_id'] = item.get('component_node_id', '')
                        logger.info(f"✅ 获取到积分信息: 当前积分 {user_info['points']}, 即将过期 {user_info['advent_points']}")

                logger.info("✅ 成功获取用户个人信息")
                return user_info
            else:
                error_msg = result.get('msg', '未知错误')
                logger.error(f"❌ 获取用户信息失败: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg
                }

        except requests.exceptions.RequestException as e:
            error_msg = f"网络请求失败: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg
            }
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            logger.error(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': error_msg
            }


    def get_encrypt_key(self) -> Dict:
        """
        获取RSA加密公钥

        Returns:
            Dict: 包含公钥信息的字典
                {
                    'success': bool,  # 是否成功
                    'public_key': str,  # 成功时的公钥(Base64编码)
                    'error': str      # 失败时的错误信息
                }
        """
        logger.info("正在获取RSA加密公钥...")

        try:
            response = requests.get(
                self.encrypt_key_url,
                headers=self.base_headers,
                cookies=self.cookies,
                timeout=30
            )
            response.raise_for_status()

            result = response.json()

            if result.get('result') == 'ok' and 'data' in result:
                public_key_base64 = result['data']
                logger.info("✅ 成功获取RSA加密公钥")
                return {
                    'success': True,
                    'public_key': public_key_base64
                }
            else:
                error_msg = result.get('msg', '未知错误')
                logger.error(f"❌ 获取公钥失败: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg
                }

        except requests.exceptions.RequestException as e:
            error_msg = f"网络请求失败: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg
            }
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg
            }

    def generate_crypto_data(self, public_key_base64: str, user_id: int, platform: int = 64) -> Dict:
        """
        生成加密数据和token

        Args:
            public_key_base64 (str): Base64编码的RSA公钥
            user_id (int): 用户ID（必需）
            platform (int): 平台标识，默认64

        Returns:
            Dict: 包含加密数据的字典
                {
                    'extra': str,      # AES加密的数据
                    'token': str,      # RSA加密的AES密钥
                    'aesKey': str      # AES密钥（用于调试）
                }
        """

        # 解码公钥
        public_key_pem = base64.b64decode(public_key_base64).decode('utf-8')

        # 生成AES密钥
        aes_key = self.encryption.generate_aes_key(32)

        # 准备明文数据
        plain_data = json.dumps({
            "user_id": user_id,
            "platform": platform
        }, separators=(',', ':'))

        # AES加密数据 (这是extra)
        encrypt_data = self.encryption.aes_encrypt(plain_data, aes_key)

        # RSA加密AES密钥 (这是请求头中的token)
        token = self.encryption.rsa_encrypt(aes_key, public_key_pem)

        logger.debug(f"User ID: {user_id}")
        logger.debug(f"Plain Data: {plain_data}")
        logger.debug(f"AES Key: {aes_key}")
        logger.debug(f"Extra: {encrypt_data}")
        logger.debug(f"Token (请求头): {token}")

        return {
            "extra": encrypt_data,
            "token": token,
            "aesKey": aes_key
        }

    def sign_in(self, user_id: int) -> Dict:
        """
        执行签到

        Args:
            user_id (int): 用户ID（必需）

        Returns:
            Dict: 签到结果
                {
                    'success': bool,  # 是否成功
                    'data': dict,     # 成功时的签到信息
                    'error': str      # 失败时的错误信息
                }
        """
        logger.info("开始签到...")

        try:
            # 1. 获取RSA公钥
            key_result = self.get_encrypt_key()
            if not key_result['success']:
                return {
                    'success': False,
                    'error': f"获取公钥失败: {key_result['error']}"
                }

            public_key_base64 = key_result['public_key']

            # 2. 生成加密数据和token
            crypto_result = self.generate_crypto_data(public_key_base64, user_id)

            # 3. 构造请求头 (使用生成的token)
            headers = self.base_headers.copy()
            headers['token'] = crypto_result['token']

            # 4. 构造请求数据
            data = {
                "encrypt": True,
                "extra": crypto_result['extra'],
                "pay_origin": "pc_ucs_rwzx_sign"
            }

            logger.debug(f"请求URL: {self.sign_in_url}")
            logger.debug(f"请求头Token: {crypto_result['token'][:50]}...")
            logger.debug(f"请求数据: {json.dumps(data, indent=2)}")

            # 5. 发送请求
            response = requests.post(
                self.sign_in_url,
                headers=headers,
                cookies=self.cookies,
                json=data,
                timeout=30
            )

            logger.debug(f"响应状态码: {response.status_code}")
            logger.debug(f"响应内容: {response.text}")

            # 6. 解析响应
            if response.status_code == 200:
                resp_data = response.json()
                if resp_data.get('result') == 'ok':
                    logger.info("✅ 签到成功!")
                    return {
                        'success': True,
                        'data': resp_data.get('data', {})
                    }
                else:
                    error_msg = resp_data.get('msg', '未知错误')
                    error_code = resp_data.get('code')
                    ext_msg = resp_data.get('ext_msg', '')

                    # 检查是否是token过期
                    if error_code == 2000000 and ext_msg == 'userNotLogin':
                        logger.error("❌ Token已过期，请重新登录")
                        return {
                            'success': False,
                            'error': 'Token已过期，请重新登录',
                            'error_type': 'token_expired'
                        }
                    # 检查是否已经签到
                    elif error_msg == 'has sign':
                        logger.info("✅ 今日已签到")
                        return {
                            'success': True,
                            'already_signed': True,
                            'data': resp_data.get('data', {}),
                            'message': '今日已签到'
                        }
                    else:
                        logger.error(f"❌ 签到失败: {error_msg}")
                        return {
                            'success': False,
                            'error': error_msg
                        }
            else:
                error_msg = f"HTTP {response.status_code}"
                logger.error(f"❌ 请求失败: {error_msg}")
                return {
                    'success': False,
                    'error': error_msg
                }

        except requests.exceptions.RequestException as e:
            error_msg = f"网络请求失败: {str(e)}"
            logger.error(f"❌ {error_msg}")
            return {
                'success': False,
                'error': error_msg
            }
        except Exception as e:
            error_msg = f"未知错误: {str(e)}"
            logger.error(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': error_msg
            }

    def lottery(self, activity_number: str = "HD2025031821201822",
                    page_number: str = "YM2025041617143388",
                    component_number: str = "ZJ2025092916515917",
                    component_node_id: str = "FN1762346087mJlk",
                    session_id: int = 2) -> Dict:
            """
            执行抽奖
            Args:
                activity_number (str): 活动编号
                page_number (str): 页面编号
                component_number (str): 组件编号
                component_node_id (str): 组件节点ID
                session_id (int): 会话ID，默认2
            Returns:
                Dict: 抽奖结果
                    {
                        'success': bool,           # 是否成功
                        'prize_name': str,         # 奖品名称
                        'reward_type': str,        # 奖品类型
                        'order_id': str,           # 订单ID
                        'reward_id': int,          # 奖品ID
                        'img': str,                # 奖品图片
                        'data': dict,              # 原始返回数据
                        'error': str,              # 失败时的错误信息
                        'error_type': str          # 错误类型（如token_expired）
                    }
            """
            logger.info("正在执行抽奖...")
            try:
                # 构造请求头
                headers = self.base_headers.copy()
                headers['referer'] = f'https://personal-act.wps.cn/rubik2/portal/{activity_number}/{page_number}?cs_from=&mk_key=JkVKsOtv4aCLMdNdAKwUGoz9tfKeFZVKyjEe&position=mac_grzx_sign'
                headers['sec-fetch-site'] = 'same-origin'
                headers['sec-fetch-mode'] = 'cors'
                headers['sec-fetch-dest'] = 'empty'
                # 构造请求数据
                data = {
                    "component_uniq_number": {
                        "activity_number": activity_number,
                        "page_number": page_number,
                        "component_number": component_number,
                        "component_node_id": component_node_id,
                        "filter_params": {
                            "cs_from": "",
                            "mk_key": "JkVKsOtv4aCLMdNdAKwUGoz9tfKeFZVKyjEe",
                            "position": "mac_grzx_sign"
                        }
                    },
                    "component_type": 45,
                    "component_action": "lottery_v2.exec",
                    "lottery_v2": {
                        "session_id": session_id
                    }
                }
                logger.debug(f"抽奖请求URL: {self.lottery_url}")
                logger.debug(f"抽奖请求数据: {json.dumps(data, indent=2, ensure_ascii=False)}")
                # 发送POST请求
                response = requests.post(
                    self.lottery_url,
                    headers=headers,
                    cookies=self.cookies,
                    json=data,
                    timeout=30
                )
                logger.debug(f"抽奖响应状态码: {response.status_code}")
                logger.debug(f"抽奖响应内容: {response.text}")
                response.raise_for_status()
                result = response.json()
                # 检查响应结果
                if result.get('result') == 'ok' and 'data' in result:
                    data_obj = result.get('data', {})
                    lottery_v2 = data_obj.get('lottery_v2', {})
                    # 检查抽奖是否成功
                    if lottery_v2.get('success'):
                        prize_name = lottery_v2.get('reward_name', '未知')
                        reward_type = lottery_v2.get('reward_type', '')
                        order_id = lottery_v2.get('order_id', '')
                        reward_id = lottery_v2.get('reward_id', 0)
                        img = lottery_v2.get('img', '')
                        logger.info(f"✅ 抽奖成功！获得: {prize_name}")
                        return {
                            'success': True,
                            'prize_name': prize_name,
                            'reward_type': reward_type,
                            'order_id': order_id,
                            'reward_id': reward_id,
                            'img': img,
                            'data': lottery_v2
                        }
                    else:
                        error_code = lottery_v2.get('error_code', 0)
                        send_msg = lottery_v2.get('send_msg', '抽奖失败')
                        logger.error(f"❌ 抽奖失败: {send_msg} (错误码: {error_code})")
                        return {
                            'success': False,
                            'error': send_msg,
                            'error_code': error_code
                        }
                else:
                    error_msg = result.get('msg', '未知错误')
                    error_code = result.get('code')
                    ext_msg = result.get('ext_msg', '')
                    # 检查是否是token过期
                    if error_code == 2000000 and ext_msg == 'userNotLogin':
                        logger.error("❌ Token已过期，请重新登录")
                        return {
                            'success': False,
                            'error': 'Token已过期，请重新登录',
                            'error_type': 'token_expired'
                        }
                    else:
                        logger.error(f"❌ 抽奖失败: {error_msg}")
                        return {
                            'success': False,
                            'error': error_msg
                        }
            except requests.exceptions.RequestException as e:
                error_msg = f"网络请求失败: {str(e)}"
                logger.error(f"❌ {error_msg}")
                return {
                    'success': False,
                    'error': error_msg
                }
            except Exception as e:
                error_msg = f"未知错误: {str(e)}"
                logger.error(f"❌ {error_msg}")
                import traceback
                traceback.print_exc()
                return {
                    'success': False,
                    'error': error_msg
                }
