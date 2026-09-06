#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy账号导入工具

将 cockpit-tools (https://github.com/jlcodes99/cockpit-tools) 管理的 WorkBuddy 账号
批量导入到本项目的 config/token.json 中的 workbuddy 节点。

支持的导入来源：
1. 自动探测本机 cockpit-tools 数据目录（默认行为）
2. 指定 cockpit-tools 数据目录或 workbuddy_accounts 目录
3. 指定单个账号 JSON 文件，或包含账号数组的 JSON 文件

账号存储兼容两种格式：
- 明文：直接包含 access_token 字段
- 加密：cockpit-tools 新版使用 AES-256-GCM 加密（字段 ciphertext/nonce），
       本工具会用本机 secure-account-storage.key 自动解密

使用示例：
    python import_accounts.py                      # 自动探测并导入
    python import_accounts.py --list               # 仅预览，不写入配置
    python import_accounts.py --path D:/xxx.json   # 从指定文件导入
    python import_accounts.py --path D:/xxx/dir    # 从指定目录导入
"""

import argparse
import base64
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

project_root = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = project_root / "config" / "token.json"

# cockpit-tools 中的账号索引文件与详情目录名
ACCOUNTS_INDEX_FILE = "workbuddy_accounts.json"
ACCOUNTS_DIR_NAME = "workbuddy_accounts"
# 加密账号使用的本地密钥文件名
KEY_FILE_NAME = "secure-account-storage.key"

try:
    from Crypto.Cipher import AES
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


def find_cockpit_data_dirs() -> List[Path]:
    """
    自动探测本机可能存在的 cockpit-tools 数据目录

    Returns:
        List[Path]: 包含 WorkBuddy 账号数据的候选目录列表
    """
    candidates: List[Path] = []
    home = Path.home()

    # 各平台应用数据根目录
    roots: List[Path] = []
    if sys.platform == 'win32':
        for env_key in ('APPDATA', 'LOCALAPPDATA'):
            value = os.environ.get(env_key)
            if value:
                roots.append(Path(value))
        # 家目录本身（cockpit-tools 数据可能在 C:/Users/xxx/.antigravity_cockpit）
        roots.append(home)
        roots.append(home / '.config')
        roots.append(home / '.local' / 'share')
    elif sys.platform == 'darwin':
        roots.append(home / 'Library' / 'Application Support')
        roots.append(home)
    else:
        roots.append(home / '.config')
        roots.append(home / '.local' / 'share')
        roots.append(home)

    for root in roots:
        if not root.is_dir():
            continue
        try:
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                name = child.name.lower()
                if 'cockpit' in name or 'agtools' in name or 'antigravity' in name:
                    if (child / ACCOUNTS_INDEX_FILE).exists() or (child / ACCOUNTS_DIR_NAME).is_dir():
                        candidates.append(child)
        except PermissionError:
            continue

    return candidates


def find_secure_key(source_dir: Path) -> Optional[Path]:
    """
    为给定账号来源目录查找解密用的本地密钥文件

    优先在来源目录及其上级目录查找，最后回退到常见的家目录路径。

    Args:
        source_dir (Path): 账号来源目录（可能是 cockpit 数据目录或 workbuddy_accounts 目录）

    Returns:
        Optional[Path]: 密钥文件路径，未找到返回 None
    """
    search_bases: List[Path] = [source_dir]
    if source_dir.name == ACCOUNTS_DIR_NAME:
        search_bases.append(source_dir.parent)
    else:
        search_bases.append(source_dir / ACCOUNTS_DIR_NAME)
    search_bases.append(source_dir.parent)

    for base in search_bases:
        candidate = base / KEY_FILE_NAME
        if candidate.is_file():
            return candidate

    # 回退：家目录下的常见位置
    home = Path.home()
    for fallback in (
        home / '.antigravity_cockpit' / KEY_FILE_NAME,
        home / '.config' / 'cockpit-tools' / KEY_FILE_NAME,
        home / '.local' / 'share' / 'cockpit-tools' / KEY_FILE_NAME,
    ):
        if fallback.is_file():
            return fallback

    return None


def decrypt_record(enc: Dict[str, Any], key: bytes) -> Optional[Dict[str, Any]]:
    """
    使用本地密钥解密 AES-256-GCM 加密的账号记录

    Args:
        enc (Dict[str, Any]): 含 ciphertext/nonce 的加密记录
        key (bytes): 32 字节 AES 密钥

    Returns:
        Optional[Dict[str, Any]]: 解密后的明文账号数据，失败返回 None
    """
    if not HAS_CRYPTO:
        return None
    try:
        nonce = base64.b64decode(enc['nonce'])
        ct = base64.b64decode(enc['ciphertext'])
        # GCM 认证标签为密文末尾 16 字节
        cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
        plain = cipher.decrypt_and_verify(ct[:-16], ct[-16:])
        return json.loads(plain.decode('utf-8'))
    except Exception as e:
        print(f"⚠️  解密失败: {e}")
        return None


def load_accounts_from_dir(directory: Path) -> List[Dict[str, Any]]:
    """
    从目录中读取 WorkBuddy 账号详情

    兼容两种传入方式：cockpit-tools 数据目录，或直接是 workbuddy_accounts 目录。
    同时兼容明文与 AES-256-GCM 加密两种存储格式。

    Args:
        directory (Path): 目录路径

    Returns:
        List[Dict[str, Any]]: 原始账号数据列表
    """
    accounts_dir = directory / ACCOUNTS_DIR_NAME
    if not accounts_dir.is_dir():
        accounts_dir = directory

    if not accounts_dir.is_dir():
        return []

    key_path = find_secure_key(directory)
    key = None
    if key_path:
        try:
            key = base64.b64decode(key_path.read_text(encoding='utf-8').strip())
        except Exception as e:
            print(f"⚠️  读取密钥失败: {e}")

    accounts: List[Dict[str, Any]] = []
    for json_file in sorted(accounts_dir.glob('*.json')):
        if json_file.name == ACCOUNTS_INDEX_FILE:
            continue
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️  跳过无法解析的文件 {json_file.name}: {e}")
            continue

        # 加密格式：含 ciphertext 字段
        if isinstance(data, dict) and data.get('ciphertext') and key:
            data = decrypt_record(data, key)
            if not data:
                continue

        if isinstance(data, dict) and data.get('access_token'):
            accounts.append(data)

    return accounts


def load_accounts_from_file(file_path: Path) -> List[Dict[str, Any]]:
    """
    从单个 JSON 文件读取账号，支持单对象、数组以及 {"accounts": [...]} 结构

    Args:
        file_path (Path): JSON 文件路径

    Returns:
        List[Dict[str, Any]]: 原始账号数据列表
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"❌ 读取文件失败: {e}")
        return []

    if isinstance(data, dict):
        # 单文件加密记录
        if data.get('ciphertext'):
            key_path = find_secure_key(file_path.parent)
            if key_path:
                key = base64.b64decode(key_path.read_text(encoding='utf-8').strip())
                dec = decrypt_record(data, key)
                if dec:
                    data = dec
        if isinstance(data.get('accounts'), list):
            data = data['accounts']
        else:
            data = [data]

    if not isinstance(data, list):
        return []

    return [item for item in data if isinstance(item, dict) and item.get('access_token')]


def convert_account(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    将 cockpit-tools 账号结构转换为本项目配置结构

    Args:
        raw (Dict[str, Any]): cockpit-tools 的账号数据

    Returns:
        Optional[Dict[str, Any]]: 转换后的账号配置，缺少令牌时返回None
    """
    access_token = raw.get('access_token')
    if not access_token:
        return None

    account_name = raw.get('nickname') or raw.get('email') or raw.get('id') or '未命名账号'

    account: Dict[str, Any] = {
        'account_name': account_name,
        'email': raw.get('email', ''),
        'access_token': access_token,
    }

    # 可选字段仅在有值时写入，避免配置中出现大量空串
    for key in ('refresh_token', 'uid', 'enterprise_id', 'domain'):
        value = raw.get(key)
        if value:
            account[key] = value

    return account


def account_identity(account: Dict[str, Any]) -> str:
    """
    生成账号唯一标识，用于导入时去重

    Args:
        account (Dict[str, Any]): 账号配置

    Returns:
        str: 唯一标识
    """
    return (account.get('uid') or account.get('email') or account.get('account_name') or '').strip().lower()


def merge_into_config(new_accounts: List[Dict[str, Any]], config_path: Path) -> Dict[str, int]:
    """
    将账号合并写入配置文件的 workbuddy 节点

    已存在的账号会更新令牌，不存在的账号追加写入

    Args:
        new_accounts (List[Dict[str, Any]]): 待导入的账号列表
        config_path (Path): 配置文件路径

    Returns:
        Dict[str, int]: 包含added和updated数量的统计字典
    """
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            config_data = json.load(f)
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_data = {}

    workbuddy_node = config_data.setdefault('workbuddy', {})
    existing: List[Dict[str, Any]] = workbuddy_node.setdefault('accounts', [])

    index_map = {account_identity(acc): idx for idx, acc in enumerate(existing) if account_identity(acc)}

    added = 0
    updated = 0

    for account in new_accounts:
        identity = account_identity(account)
        if identity and identity in index_map:
            target = existing[index_map[identity]]
            # 保留用户自定义的账号名称，只更新令牌等认证信息
            for key, value in account.items():
                if key == 'account_name':
                    continue
                target[key] = value
            updated += 1
        else:
            existing.append(account)
            if identity:
                index_map[identity] = len(existing) - 1
            added += 1

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=2)

    return {'added': added, 'updated': updated}


def collect_accounts() -> List[Dict[str, Any]]:
    """
    自动探测 cockpit-tools 数据目录并采集账号（已转换、去重）

    Returns:
        List[Dict[str, Any]]: 转换后的账号配置列表，无可用来源时返回空列表
    """
    candidates = find_cockpit_data_dirs()
    if not candidates:
        return []

    raw_accounts: List[Dict[str, Any]] = []
    for candidate in candidates:
        raw_accounts.extend(load_accounts_from_dir(candidate))

    accounts: List[Dict[str, Any]] = []
    seen = set()
    for raw in raw_accounts:
        converted = convert_account(raw)
        if not converted:
            continue
        identity = account_identity(converted)
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        accounts.append(converted)

    return accounts


def sync_accounts(config_path: Optional[Path] = None, quiet: bool = False) -> Optional[Dict[str, int]]:
    """
    从本机 cockpit-tools 同步账号到配置文件（签到前的自动刷新入口）

    自动探测数据目录、读取并解密账号、去重后合并写入配置。
    任何异常都不抛出，保证不影响签到主流程。

    Args:
        config_path (Optional[Path]): 配置文件路径，默认项目根目录 config/token.json
        quiet (bool): True 时不输出任何提示信息

    Returns:
        Optional[Dict[str, int]]: 同步统计 {'added': n, 'updated': n}；
                                  未找到 cockpit-tools 或无账号时返回 None
    """
    log = (lambda *a, **k: None) if quiet else print
    try:
        accounts = collect_accounts()
        if not accounts:
            return None
        stats = merge_into_config(accounts, config_path or CONFIG_PATH)
        log(f"✅ 同步完成: 新增 {stats['added']} 个，更新 {stats['updated']} 个")
        return stats
    except Exception as e:
        log(f"⚠️  同步失败（不影响签到）: {e}")
        return None


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='WorkBuddy账号导入工具')
    parser.add_argument('--path', help='指定 cockpit-tools 数据目录或账号 JSON 文件路径')
    parser.add_argument('--list', action='store_true', help='仅预览待导入账号，不写入配置文件')
    parser.add_argument('--config', help=f'指定配置文件路径，默认 {CONFIG_PATH}')
    args = parser.parse_args()

    config_path = Path(args.config) if args.config else CONFIG_PATH

    if args.path:
        source = Path(args.path).expanduser()
        if not source.exists():
            print(f"❌ 路径不存在: {source}")
            sys.exit(1)

        if source.is_dir():
            raw_accounts = load_accounts_from_dir(source)
        else:
            raw_accounts = load_accounts_from_file(source)

        print(f"📂 来源: {source}")

        accounts: List[Dict[str, Any]] = []
        seen = set()
        for raw in raw_accounts:
            converted = convert_account(raw)
            if not converted:
                continue
            identity = account_identity(converted)
            if identity and identity in seen:
                continue
            if identity:
                seen.add(identity)
            accounts.append(converted)
    else:
        print("🔍 正在自动探测 cockpit-tools 数据目录...")
        candidates = find_cockpit_data_dirs()

        if not candidates:
            print("❌ 未找到 cockpit-tools 数据目录")
            print("   请使用 --path 手动指定账号目录或导出的 JSON 文件，例如：")
            print("   python import_accounts.py --path \"C:/Users/你的用户名/.antigravity_cockpit\"")
            sys.exit(1)

        for candidate in candidates:
            found = load_accounts_from_dir(candidate)
            if found:
                print(f"📂 来源: {candidate} (发现 {len(found)} 个账号)")
        accounts = collect_accounts()

    if not accounts:
        print("❌ 未找到任何包含 access_token 的账号数据")
        sys.exit(1)

    print(f"\n共解析到 {len(accounts)} 个账号:")
    for idx, account in enumerate(accounts, 1):
        token_preview = account['access_token'][:12] + '...'
        print(f"  {idx}. {account['account_name']} | {account.get('email', '-')} | token: {token_preview}")

    if args.list:
        print("\n👀 预览模式，未写入配置文件")
        return

    stats = merge_into_config(accounts, config_path)
    print(f"\n✅ 导入完成: 新增 {stats['added']} 个，更新 {stats['updated']} 个")
    print(f"📝 配置文件: {config_path}")


if __name__ == '__main__':
    main()
