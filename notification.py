#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
青龙面板通知推送模块

支持的推送方式：
- Bark 推送
- Server酱 推送
- Server酱 Turbo 推送
- Cool Push 推送
- Qmsg酱 推送
- Telegram 推送
- 飞书 推送
- 钉钉 推送
- 企业微信群机器人 推送
- 企业微信应用消息 推送
- PushPlus 推送
- Gotify 推送
- Ntfy 推送
- PushDeer 推送

配置参数说明（需要在青龙面板的 config.sh 中设置或通过环境变量设置）：
详见各平台对应的配置说明

使用示例：
    from notification import send_notification, NotificationLevel, NotificationSound

    # 基础推送（自动使用所有已配置的平台）
    send_notification("测试标题", "测试内容")

    # 自定义级别和声音
    send_notification(
        "重要通知",
        "这是一条重要消息",
        level=NotificationLevel.TIME_SENSITIVE,
        sound=NotificationSound.ALARM
    )

Author: Assistant
Date: 2025-12-08
参考项目:https://github.com/Sitoi/dailycheckin 的推送相关内容
"""

import os
import json
import requests
import logging
import base64
import hashlib
import hmac
import time
from typing import Optional, Dict, Any
from urllib.parse import quote_plus


# 推送级别常量
class NotificationLevel:
    """推送级别常量"""
    ACTIVE = "active"           # 默认级别，立即亮屏显示通知
    TIME_SENSITIVE = "timeSensitive"  # 时效性通知，即使在专注模式下也会显示
    PASSIVE = "passive"         # 被动通知，不会立即显示，需要用户主动查看


# 推送声音常量
class NotificationSound:
    """推送声音常量"""
    ALARM = "alarm"
    ANTICIPATE = "anticipate"
    BELL = "bell"
    BIRDSONG = "birdsong"      # 默认
    BLOOM = "bloom"
    CALYPSO = "calypso"
    CHIME = "chime"
    CHOO = "choo"
    DESCENT = "descent"
    ELECTRONIC = "electronic"
    FANFARE = "fanfare"
    GLASS = "glass"
    GOTOSLEEP = "gotosleep"
    HEALTHNOTIFICATION = "healthnotification"
    HORN = "horn"
    LADDER = "ladder"
    MAILSENT = "mailsent"
    MINUET = "minuet"
    MULTIWAYINVITATION = "multiwayinvitation"
    NEWMAIL = "newmail"
    NEWSFLASH = "newsflash"
    NOIR = "noir"
    PAYMENTSUCCESS = "paymentsuccess"
    SHAKE = "shake"
    SHERWOODFOREST = "sherwoodforest"
    SILENCE = "silence"
    SPELL = "spell"
    SUSPENSE = "suspense"
    TELEGRAPH = "telegraph"
    TIPTOES = "tiptoes"
    TYPEWRITERS = "typewriters"
    UPDATE = "update"


class NotificationManager:
    """青龙面板通知推送管理器"""

    def __init__(self):
        """初始化推送管理器"""
        self.logger = logging.getLogger("NotificationManager")
        self.config_from_file = self._load_config_from_file()

        self.bark_config = self._load_bark_config()
        self.server_config = self._load_server_config()
        self.coolpush_config = self._load_coolpush_config()
        self.qmsg_config = self._load_qmsg_config()
        self.telegram_config = self._load_telegram_config()
        self.feishu_config = self._load_feishu_config()
        self.dingtalk_config = self._load_dingtalk_config()
        self.qywx_config = self._load_qywx_config()
        self.pushplus_config = self._load_pushplus_config()
        self.gotify_config = self._load_gotify_config()
        self.ntfy_config = self._load_ntfy_config()
        self.pushdeer_config = self._load_pushdeer_config()

    def _load_config_from_file(self) -> Dict:
        """从JSON文件中加载配置"""
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config', 'notification.json')
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    self.logger.error(f"❌ 配置文件 {config_path} 格式错误")
                    return {}
        return {}

    def _get_config_value(self, service: str, key: str, env_var: str, default: Any = None) -> Any:
        """
        获取配置值，优先级: 文件 > 环境变量 > 默认值
        """
        # 1. 从文件配置中获取
        file_config = self.config_from_file.get(service, {})
        value = file_config.get(key)

        # 如果值是字符串，去除首尾空格
        if isinstance(value, str):
            value = value.strip()

        # 文件中有非空值，则直接返回
        if value is not None and value != '':
            return value

        # 2. 从环境变量中获取
        env_value = os.environ.get(env_var, '').strip()
        if env_value:
            # 对布尔类型的环境变量进行特殊处理
            if isinstance(default, bool):
                return env_value.lower() == 'true'
            return env_value

        # 3. 返回默认值
        return default


    def _load_bark_config(self) -> Dict[str, str]:
        """加载Bark配置"""
        return {
            'push': self._get_config_value('bark', 'push', 'BARK_PUSH', ''),
            'icon': self._get_config_value('bark', 'icon', 'BARK_ICON', ''),
            'sound': self._get_config_value('bark', 'sound', 'BARK_SOUND', 'birdsong'),
            'group': self._get_config_value('bark', 'group', 'BARK_GROUP', ''),
            'level': self._get_config_value('bark', 'level', 'BARK_LEVEL', ''),
            'url': self._get_config_value('bark', 'url', 'BARK_URL', ''),
        }

    def _load_server_config(self) -> Dict[str, str]:
        """加载Server酱配置"""
        return {
            'sckey': self._get_config_value('server', 'sckey', 'SCKEY', ''),
            'sendkey': self._get_config_value('server', 'sendkey', 'SENDKEY', ''),
        }

    def _load_coolpush_config(self) -> Dict[str, Any]:
        """加载CoolPush配置"""
        return {
            'skey': self._get_config_value('coolpush', 'skey', 'COOLPUSH_SKEY', ''),
            'qq': self._get_config_value('coolpush', 'qq', 'COOLPUSH_QQ', True),
            'wx': self._get_config_value('coolpush', 'wx', 'COOLPUSH_WX', False),
            'email': self._get_config_value('coolpush', 'email', 'COOLPUSH_EMAIL', False),
        }

    def _load_qmsg_config(self) -> Dict[str, str]:
        """加载Qmsg酱配置"""
        return {
            'key': self._get_config_value('qmsg', 'key', 'QMSG_KEY', ''),
            'type': self._get_config_value('qmsg', 'type', 'QMSG_TYPE', 'private'),
        }

    def _load_telegram_config(self) -> Dict[str, str]:
        """加载Telegram配置"""
        return {
            'bot_token': self._get_config_value('telegram', 'bot_token', 'TG_BOT_TOKEN', ''),
            'user_id': self._get_config_value('telegram', 'user_id', 'TG_USER_ID', ''),
            'api_host': self._get_config_value('telegram', 'api_host', 'TG_API_HOST', ''),
            'proxy': self._get_config_value('telegram', 'proxy', 'TG_PROXY', ''),
        }

    def _load_feishu_config(self) -> Dict[str, str]:
        """加载飞书配置"""
        return {
            'key': self._get_config_value('feishu', 'key', 'FSKEY', ''),
        }

    def _load_dingtalk_config(self) -> Dict[str, str]:
        """加载钉钉配置"""
        return {
            'access_token': self._get_config_value('dingtalk', 'access_token', 'DINGTALK_ACCESS_TOKEN', ''),
            'secret': self._get_config_value('dingtalk', 'secret', 'DINGTALK_SECRET', ''),
        }

    def _load_qywx_config(self) -> Dict[str, str]:
        """加载企业微信配置"""
        return {
            'key': self._get_config_value('qywx', 'key', 'QYWX_KEY', ''),
            'corpid': self._get_config_value('qywx', 'corpid', 'QYWX_CORPID', ''),
            'agentid': self._get_config_value('qywx', 'agentid', 'QYWX_AGENTID', ''),
            'corpsecret': self._get_config_value('qywx', 'corpsecret', 'QYWX_CORPSECRET', ''),
            'touser': self._get_config_value('qywx', 'touser', 'QYWX_TOUSER', ''),
            'media_id': self._get_config_value('qywx', 'media_id', 'QYWX_MEDIA_ID', ''),
            'origin': self._get_config_value('qywx', 'origin', 'QYWX_ORIGIN', ''),
        }

    def _load_pushplus_config(self) -> Dict[str, str]:
        """加载PushPlus配置"""
        return {
            'token': self._get_config_value('pushplus', 'token', 'PUSHPLUS_TOKEN', ''),
            'topic': self._get_config_value('pushplus', 'topic', 'PUSHPLUS_TOPIC', ''),
        }

    def _load_gotify_config(self) -> Dict[str, str]:
        """加载Gotify配置"""
        return {
            'url': self._get_config_value('gotify', 'url', 'GOTIFY_URL', ''),
            'token': self._get_config_value('gotify', 'token', 'GOTIFY_TOKEN', ''),
            'priority': self._get_config_value('gotify', 'priority', 'GOTIFY_PRIORITY', '3'),
        }

    def _load_ntfy_config(self) -> Dict[str, str]:
        """加载Ntfy配置"""
        return {
            'url': self._get_config_value('ntfy', 'url', 'NTFY_URL', 'https://ntfy.sh'),
            'topic': self._get_config_value('ntfy', 'topic', 'NTFY_TOPIC', ''),
            'priority': self._get_config_value('ntfy', 'priority', 'NTFY_PRIORITY', '3'),
        }

    def _load_pushdeer_config(self) -> Dict[str, str]:
        """加载PushDeer配置"""
        return {
            'pushkey': self._get_config_value('pushdeer', 'pushkey', 'PUSHDEER_PUSHKEY', ''),
            'url': self._get_config_value('pushdeer', 'url', 'PUSHDEER_URL', 'https://api2.pushdeer.com/message/push'),
            'type': self._get_config_value('pushdeer', 'type', 'PUSHDEER_TYPE', 'text'),
        }

    def is_bark_enabled(self) -> bool:
        """检查Bark推送是否已启用"""
        return bool(self.bark_config.get('push'))

    def is_server_enabled(self) -> bool:
        """检查Server酱推送是否已启用"""
        return bool(self.server_config.get('sckey') or self.server_config.get('sendkey'))

    def is_coolpush_enabled(self) -> bool:
        """检查CoolPush推送是否已启用"""
        return bool(self.coolpush_config.get('skey'))

    def is_qmsg_enabled(self) -> bool:
        """检查Qmsg酱推送是否已启用"""
        return bool(self.qmsg_config.get('key'))

    def is_telegram_enabled(self) -> bool:
        """检查Telegram推送是否已启用"""
        return bool(self.telegram_config.get('bot_token') and self.telegram_config.get('user_id'))

    def is_feishu_enabled(self) -> bool:
        """检查飞书推送是否已启用"""
        return bool(self.feishu_config.get('key'))

    def is_dingtalk_enabled(self) -> bool:
        """检查钉钉推送是否已启用"""
        return bool(self.dingtalk_config.get('access_token') and self.dingtalk_config.get('secret'))

    def is_qywx_robot_enabled(self) -> bool:
        """检查企业微信群机器人推送是否已启用"""
        return bool(self.qywx_config.get('key'))

    def is_qywx_app_enabled(self) -> bool:
        """检查企业微信应用消息推送是否已启用"""
        return bool(
            self.qywx_config.get('corpid') and
            self.qywx_config.get('agentid') and
            self.qywx_config.get('corpsecret') and
            self.qywx_config.get('touser')
        )

    def is_pushplus_enabled(self) -> bool:
        """检查PushPlus推送是否已启用"""
        return bool(self.pushplus_config.get('token'))

    def is_gotify_enabled(self) -> bool:
        """检查Gotify推送是否已启用"""
        return bool(self.gotify_config.get('url') and self.gotify_config.get('token'))

    def is_ntfy_enabled(self) -> bool:
        """检查Ntfy推送是否已启用"""
        return bool(self.ntfy_config.get('topic'))

    def is_pushdeer_enabled(self) -> bool:
        """检查PushDeer推送是否已启用"""
        return bool(self.pushdeer_config.get('pushkey'))

    def send(self, title: str, content: str, level: Optional[str] = None,
             sound: Optional[str] = None, group: Optional[str] = None,
             url: Optional[str] = None, timeout: int = 10):
        """
        统一发送所有已启用的通知

        Args:
            title (str): 推送标题
            content (str): 推送内容
            level (Optional[str]): 推送级别 (Bark专用)
            sound (Optional[str]): 推送声音 (Bark专用)
            group (Optional[str]): 推送分组 (Bark专用)
            url (Optional[str]): 跳转链接 (Bark专用)
            timeout (int): 请求超时时间
        """
        if self.is_bark_enabled():
            self.send_bark_notification(title, content, timeout, level, sound, group, url)
        if self.is_server_enabled():
            self.send_server_notification(title, content, timeout)
        if self.is_coolpush_enabled():
            self.send_coolpush_notification(title, content, timeout)
        if self.is_qmsg_enabled():
            self.send_qmsg_notification(content, timeout)
        if self.is_telegram_enabled():
            self.send_telegram_notification(title, content, timeout)
        if self.is_feishu_enabled():
            self.send_feishu_notification(title, content, timeout)
        if self.is_dingtalk_enabled():
            self.send_dingtalk_notification(title, content, timeout)
        if self.is_qywx_robot_enabled():
            self.send_qywx_robot_notification(content, timeout)
        if self.is_qywx_app_enabled():
            self.send_qywx_app_notification(title, content, timeout)
        if self.is_pushplus_enabled():
            self.send_pushplus_notification(title, content, timeout)
        if self.is_pushdeer_enabled():
            self.send_pushdeer_notification(title, content, timeout)
        if self.is_gotify_enabled():
            self.send_gotify_notification(title, content, timeout)
        if self.is_ntfy_enabled():
            self.send_ntfy_notification(title, content, timeout)

    def send_server_notification(self, title: str, content: str, timeout: int = 10) -> bool:
        """发送Server酱推送"""
        sckey = self.server_config.get('sckey')
        sendkey = self.server_config.get('sendkey')

        if not (sckey or sendkey):
            self.logger.warning("Server酱推送未启用")
            return False

        data = {'text': title, 'desp': content.replace("\n", "\n\n")}

        try:
            if sckey:
                self.logger.info("正在发送Server酱(SCKEY)推送")
                url = f"https://sc.ftqq.com/{sckey}.send"
                response = requests.post(url, data=data, timeout=timeout)
                if response.json().get("errno") == 0:
                    self.logger.info("✅ Server酱(SCKEY)推送成功")
                else:
                    self.logger.error(f"❌ Server酱(SCKEY)推送失败: {response.text}")

            if sendkey:
                self.logger.info("正在发送Server酱(SENDKEY)推送")
                url = f"https://sctapi.ftqq.com/{sendkey}.send"
                response = requests.post(url, data=data, timeout=timeout)
                if response.json().get("code") == 0:
                    self.logger.info("✅ Server酱(SENDKEY)推送成功")
                else:
                    self.logger.error(f"❌ Server酱(SENDKEY)推送失败: {response.text}")

            return True
        except Exception as e:
            self.logger.error(f"❌ Server酱推送异常: {e}")
            return False

    def send_coolpush_notification(self, title: str, content: str, timeout: int = 10) -> bool:
        """发送CoolPush推送"""
        if not self.is_coolpush_enabled():
            self.logger.warning("CoolPush推送未启��")
            return False

        skey = self.coolpush_config.get('skey')
        params = {'c': content, 't': title}

        try:
            self.logger.info("正在发送CoolPush推送")
            base_url = f"https://push.xuthus.cc"
            if self.coolpush_config.get('qq'):
                requests.post(f"{base_url}/send/{skey}", params=params, timeout=timeout)
            if self.coolpush_config.get('wx'):
                requests.post(f"{base_url}/wx/{skey}", params=params, timeout=timeout)
            if self.coolpush_config.get('email'):
                requests.post(f"{base_url}/email/{skey}", params=params, timeout=timeout)
            self.logger.info("✅ CoolPush推送已提交")
            return True
        except Exception as e:
            self.logger.error(f"❌ CoolPush推送异常: {e}")
            return False

    def send_qmsg_notification(self, content: str, timeout: int = 10) -> bool:
        """发送Qmsg酱推送"""
        if not self.is_qmsg_enabled():
            self.logger.warning("Qmsg酱推送未启用")
            return False

        key = self.qmsg_config.get('key')
        qmsg_type = self.qmsg_config.get('type', 'private')
        url = f"https://qmsg.zendee.cn/{qmsg_type}/{key}"
        params = {'msg': content}

        try:
            self.logger.info("正在发送Qmsg酱推送")
            response = requests.get(url, params=params, timeout=timeout)
            if response.json().get("success"):
                self.logger.info("✅ Qmsg酱推送成功")
                return True
            else:
                self.logger.error(f"❌ Qmsg酱推送失败: {response.json().get('reason')}")
                return False
        except Exception as e:
            self.logger.error(f"❌ Qmsg酱推送异常: {e}")
            return False

    def send_telegram_notification(self, title: str, content: str, timeout: int = 10) -> bool:
        """发送Telegram推送"""
        if not self.is_telegram_enabled():
            self.logger.warning("Telegram推送未启用")
            return False

        bot_token = self.telegram_config['bot_token']
        user_id = self.telegram_config['user_id']
        api_host = self.telegram_config.get('api_host')
        proxy = self.telegram_config.get('proxy')

        message = f"<b>{title}</b>\n\n{content}"
        url = f"https://{api_host}/bot{bot_token}/sendMessage" if api_host else f"https://api.telegram.org/bot{bot_token}/sendMessage"

        data = {
            'chat_id': user_id,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': 'true'
        }
        proxies = {'http': proxy, 'https': proxy} if proxy else None

        try:
            self.logger.info("正在发送Telegram推送")
            response = requests.post(url, data=data, proxies=proxies, timeout=timeout)
            if response.json().get('ok'):
                self.logger.info("✅ Telegram推送成功")
                return True
            else:
                self.logger.error(f"❌ Telegram推送失败: {response.text}")
                return False
        except Exception as e:
            self.logger.error(f"❌ Telegram推送异常: {e}")
            return False

    def send_feishu_notification(self, title: str, content: str, timeout: int = 10) -> bool:
        """发送飞书机器人推送"""
        if not self.is_feishu_enabled():
            self.logger.warning("飞书推送未启用")
            return False

        key = self.feishu_config['key']
        url = f"https://open.feishu.cn/open-apis/bot/v2/hook/{key}"
        data = {
            "msg_type": "text",
            "content": {
                "text": f"{title}\n\n{content}"
            }
        }

        try:
            self.logger.info("正在发送飞书推送")
            response = requests.post(url, json=data, timeout=timeout)
            if response.json().get("StatusCode") == 0:
                self.logger.info("✅ 飞书推送成功")
                return True
            else:
                self.logger.error(f"❌ 飞书推送失败: {response.text}")
                return False
        except Exception as e:
            self.logger.error(f"❌ 飞书推送异常: {e}")
            return False

    def send_dingtalk_notification(self, title: str, content: str, timeout: int = 10) -> bool:
        """发送钉钉机器人推送"""
        if not self.is_dingtalk_enabled():
            self.logger.warning("钉钉推送未启用")
            return False

        access_token = self.dingtalk_config['access_token']
        secret = self.dingtalk_config['secret']

        timestamp = str(round(time.time() * 1000))
        secret_enc = secret.encode('utf-8')
        string_to_sign = f'{timestamp}\n{secret}'
        string_to_sign_enc = string_to_sign.encode('utf-8')
        hmac_code = hmac.new(secret_enc, string_to_sign_enc, digestmod=hashlib.sha256).digest()
        sign = quote_plus(base64.b64encode(hmac_code))

        url = f"https://oapi.dingtalk.com/robot/send?access_token={access_token}&timestamp={timestamp}&sign={sign}"
        data = {
            "msgtype": "text",
            "text": {
                "content": f"{title}\n\n{content}"
            }
        }

        try:
            self.logger.info("正在发送钉钉推送")
            response = requests.post(url, json=data, timeout=timeout)
            if response.json().get("errcode") == 0:
                self.logger.info("✅ 钉钉推送成功")
                return True
            else:
                self.logger.error(f"❌ 钉钉推送失败: {response.text}")
                return False
        except Exception as e:
            self.logger.error(f"❌ 钉钉推送异常: {e}")
            return False

    def send_qywx_robot_notification(self, content: str, timeout: int = 10) -> bool:
        """发送企业微信群机器人推送"""
        if not self.is_qywx_robot_enabled():
            self.logger.warning("企业微信群机器人推送未启用")
            return False

        key = self.qywx_config['key']
        url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={key}"
        data = {"msgtype": "text", "text": {"content": content}}

        try:
            self.logger.info("正在发送企业微信群机器人推送")
            response = requests.post(url, json=data, timeout=timeout)
            if response.json().get("errcode") == 0:
                self.logger.info("✅ 企业微信群机器人推送成功")
                return True
            else:
                self.logger.error(f"❌ 企业微信群机器��推送失败: {response.text}")
                return False
        except Exception as e:
            self.logger.error(f"❌ 企业微信群机器人推送异常: {e}")
            return False

    def send_qywx_app_notification(self, title: str, content: str, timeout: int = 10) -> bool:
        """发送企业微信应用消息推送"""
        if not self.is_qywx_app_enabled():
            self.logger.warning("企业微信应用消息推送未启用")
            return False

        corpid = self.qywx_config['corpid']
        corpsecret = self.qywx_config['corpsecret']
        agentid = self.qywx_config['agentid']
        touser = self.qywx_config['touser']
        media_id = self.qywx_config.get('media_id')

        try:
            # 获取 access_token
            token_url = f"https://qyapi.weixin.qq.com/cgi-bin/gettoken?corpid={corpid}&corpsecret={corpsecret}"
            token_res = requests.get(token_url, timeout=timeout).json()
            access_token = token_res.get('access_token')
            if not access_token:
                self.logger.error(f"❌ 企业微信应用消息获取token失败: {token_res.get('errmsg')}")
                return False

            send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={access_token}"

            if media_id:
                data = {
                    "touser": touser,
                    "msgtype": "mpnews",
                    "agentid": agentid,
                    "mpnews": {
                        "articles": [{
                            "title": title,
                            "thumb_media_id": media_id,
                            "content": content.replace("\n", "<br>"),
                            "digest": content
                        }]
                    }
                }
            else:
                data = {
                    "touser": touser,
                    "msgtype": "textcard",
                    "agentid": agentid,
                    "textcard": {
                        "title": title,
                        "description": content,
                        "url": "https://github.com/ZaiZaiCat/ZaiZaiCat-Checkin",
                        "btntxt": "详情"
                    }
                }

            self.logger.info("正在发送企业微信应用消息推送")
            response = requests.post(send_url, json=data, timeout=timeout)
            if response.json().get("errcode") == 0:
                self.logger.info("✅ 企业微信应用消息推送成功")
                return True
            else:
                self.logger.error(f"❌ 企业微信应用消息推送失败: {response.text}")
                return False
        except Exception as e:
            self.logger.error(f"❌ 企业微信应用消息推送异常: {e}")
            return False

    def send_pushplus_notification(self, title: str, content: str, timeout: int = 10) -> bool:
        """发送PushPlus推送"""
        if not self.is_pushplus_enabled():
            self.logger.warning("PushPlus推送未启用")
            return False

        token = self.pushplus_config['token']
        topic = self.pushplus_config.get('topic')

        data = {
            "token": token,
            "title": title,
            "content": content.replace("\n", "<br>"),
            "template": "html"
        }
        if topic:
            data['topic'] = topic

        url = "http://www.pushplus.plus/send"

        try:
            self.logger.info("正在发送PushPlus推送")
            response = requests.post(url, json=data, timeout=timeout)
            if response.json().get("code") == 200:
                self.logger.info("✅ PushPlus推送成功")
                return True
            else:
                self.logger.error(f"❌ PushPlus推送失败: {response.text}")
                return False
        except Exception as e:
            self.logger.error(f"❌ PushPlus推送异常: {e}")
            return False

    def send_gotify_notification(self, title: str, content: str, timeout: int = 10) -> bool:
        """发送Gotify推送"""
        if not self.is_gotify_enabled():
            self.logger.warning("Gotify推送未启用")
            return False

        base_url = self.gotify_config['url']
        token = self.gotify_config['token']
        priority = self.gotify_config.get('priority', '3')

        url = f"{base_url}/message?token={token}"
        data = {
            "title": title,
            "message": content,
            "priority": int(priority)
        }

        try:
            self.logger.info("正在发送Gotify推送")
            response = requests.post(url, json=data, timeout=timeout)
            if response.json().get("id"):
                self.logger.info("✅ Gotify推送成功")
                return True
            else:
                self.logger.error(f"❌ Gotify推送失败: {response.text}")
                return False
        except Exception as e:
            self.logger.error(f"❌ Gotify推送异常: {e}")
            return False

    def send_ntfy_notification(self, title: str, content: str, timeout: int = 10) -> bool:
        """发送Ntfy推送"""
        if not self.is_ntfy_enabled():
            self.logger.warning("Ntfy推送未启用")
            return False

        base_url = self.ntfy_config.get('url', 'https://ntfy.sh')
        topic = self.ntfy_config['topic']
        priority = self.ntfy_config.get('priority', '3')

        url = f"{base_url}/{topic}"
        headers = {
            'Title': title.encode('utf-8'),
            'Priority': priority,
            'Tags': 'tada'
        }

        try:
            self.logger.info("正在发送Ntfy推送")
            response = requests.post(url, data=content.encode('utf-8'), headers=headers, timeout=timeout)
            response.raise_for_status()
            self.logger.info("✅ Ntfy推送成功")
            return True
        except Exception as e:
            self.logger.error(f"❌ Ntfy推送异常: {e}")
            return False



    def send_bark_notification(self, title: str, content: str, timeout: int = 10,
                               level: Optional[str] = None, sound: Optional[str] = None,
                               group: Optional[str] = None, url: Optional[str] = None) -> bool:
        """
        发送Bark推送

        Args:
            title (str): 推送标题
            content (str): 推送内容
            timeout (int): 请求超时时间
            level (Optional[str]): 推送级别
            sound (Optional[str]): 推送声音
            group (Optional[str]): 推送分组
            url (Optional[str]): 跳转链接

        Returns:
            bool: 推送是否成功
        """
        if not self.is_bark_enabled():
            self.logger.warning("Bark推送未启用")
            return False

        bark_push = self.bark_config.get('push')
        base_url = self.bark_config.get('url', 'https://api.day.app').rstrip('/')

        url_path = f"{base_url}/{bark_push}" if not bark_push.startswith('http') else bark_push

        data = {
            "title": title,
            "body": content,
            "sound": sound or self.bark_config.get('sound'),
            "group": group or self.bark_config.get('group'),
            "level": level or self.bark_config.get('level'),
            "url": url or self.bark_config.get('url'),
            "icon": self.bark_config.get('icon')
        }
        # 移除None值的键
        data = {k: v for k, v in data.items() if v is not None}

        try:
            self.logger.info("正在发送Bark推送")
            response = requests.post(url_path, json=data, timeout=timeout)
            if response.json().get('code') == 200:
                self.logger.info("✅ Bark推送成功")
                return True
            else:
                self.logger.error(f"❌ Bark推送失败: {response.text}")
                return False
        except Exception as e:
            self.logger.error(f"❌ Bark推送异常: {e}")
            return False

    def send_pushdeer_notification(self, title: str, content: str, timeout: int = 10) -> bool:
        """发送 PushDeer 推送"""
        if not self.is_pushdeer_enabled():
            self.logger.warning("PushDeer 推送未启用")
            return False

        pushkey = self.pushdeer_config.get('pushkey')
        url = self.pushdeer_config.get('url', 'https://api2.pushdeer.com/message/push').rstrip('/')
        ptype = self.pushdeer_config.get('type', 'text')

        data = {
            'pushkey': pushkey,
            'text': title or '',
            'desp': content or '',
            'type': ptype
        }

        try:
            self.logger.info("正在发送 PushDeer 推送")
            response = requests.post(url, data=data, timeout=timeout)
            # 常见官方在线版返回 status_code 200 表示提交成功；进一步尝试解析 JSON
            if response.status_code == 200:
                try:
                    j = response.json()
                    # 新旧版本可能有不同字段，尽量通用判断
                    if j.get('success') is True or j.get('code') == 0 or j.get('message'):
                        self.logger.info("✅ PushDeer 推送已提交")
                        return True
                except Exception:
                    # 非 json 响应也视为提交成功
                    self.logger.info("✅ PushDeer 推送已提交 (非JSON响应)")
                    return True

                # 如果解析后没有明显成功字段，仍以 200 作为成功提交的标志
                self.logger.info("✅ PushDeer 推送已提交")
                return True
            else:
                self.logger.error(f"❌ PushDeer 推送失败: {response.status_code} {response.text}")
                return False
        except Exception as e:
            self.logger.error(f"❌ PushDeer 推送异常: {e}")
            return False


# 创建全局通知管理器实例
notification_manager = NotificationManager()


def send_notification(title: str, content: str, level: Optional[str] = None,
                     sound: Optional[str] = None, group: Optional[str] = None,
                     url: Optional[str] = None):
    """
    便捷函数：发送通知

    Args:
        title (str): 推送标题
        content (str): 推送内容
        level (Optional[str]): 推送级别 (Bark专用)
        sound (Optional[str]): 推送声音 (Bark专用)
        group (Optional[str]): 推送分组 (Bark专用)
        url (Optional[str]): 跳转链接 (Bark专用)
    """
    notification_manager.send(title, content, level=level, sound=sound, group=group, url=url)


if __name__ == "__main__":
    """测试推送功能"""
    import sys

    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 检查是否有任何推送方式被启用
    if not any([
        notification_manager.is_bark_enabled(),
        notification_manager.is_server_enabled(),
        notification_manager.is_coolpush_enabled(),
        notification_manager.is_qmsg_enabled(),
        notification_manager.is_telegram_enabled(),
        notification_manager.is_feishu_enabled(),
        notification_manager.is_dingtalk_enabled(),
        notification_manager.is_qywx_robot_enabled(),
        notification_manager.is_qywx_app_enabled(),
        notification_manager.is_pushplus_enabled(),
        notification_manager.is_gotify_enabled(),
        notification_manager.is_ntfy_enabled(),
        notification_manager.is_pushdeer_enabled(),
    ]):
        print("❌ 未配置任何推送方式，请检查环境变量")
        sys.exit(1)

    print("🧪 开始测试推送...\n")

    # 测试1: 基础推送
    print("测试1: 基础推送")
    send_notification("📱 青龙面板测试", "这是一条测试推送消息")
    print("基础推送已发送\n")

    # 测试2: 自定义级别和声音 (主要对Bark有效)
    print("测试2: 自定义推送（时效性通知 + 警报声）")
    send_notification(
        "🔔 重要通知",
        "这是一条时效性通知，部分平台（如Bark）会特殊处理",
        level=NotificationLevel.TIME_SENSITIVE,
        sound=NotificationSound.ALARM
    )
    print("自定义推送已发送\n")

    # 测试3: 任务摘要
    print("测试3: 任务摘要")
    task_title = "✅ 上海云媒体任务 - 部分成功"
    task_content = """📊 执行统计:
✅ 成功: 3 个账号
❌ 失败: 1 个账号
📈 总计: 4 个账号

📝 详情: 部分账号token已过期"""
    send_notification(task_title, task_content)
    print("任务摘要已发送\n")

    # 测试4: 错误通知
    print("测试4: 错误通知")
    error_title = "❌ 什么值得买任务 - 执行错误"
    error_content = """💥 发生错误:
👤 账号: 测试账号1
❌ 错误: 网络连接超时"""
    send_notification(error_title, error_content)
    print("错误通知已发送\n")

    print("🎉 测试完成")
