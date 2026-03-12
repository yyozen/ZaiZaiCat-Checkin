# WPS自动签到脚本

## ⚠️ 重要提示

**获取Cookie和User ID的正确方法：**

1. 🔑 **Cookie获取建议**：请抓取页面请求接口的Cookie，而不是浏览器地址栏的Cookie
   - 原因：接口请求的Cookie通常包含完整的认证信息，包括 `uid` 字段
   - 这样可以确保Cookie中包含 `user_id`，便于配置

2. 📝 **配置步骤**：
   - 先抓取签到接口的Cookie（包含 `uid=数字` 字段）
   - 从Cookie中提取 `uid` 的值作为 `user_id`
   - 将完整的Cookie和提取的 `user_id` 一起填写到配置文件中

3. ✅ **配置检查**：
   - 确保Cookie中包含 `uid` 字段
   - 确保配置文件中的 `user_id` 与Cookie中的 `uid` 值一致


## 功能说明

本脚本用于自动执行 WPS 多个活动页面的签到、试用和抽奖任务，支持多账号管理和推送通知功能。

### 主要功能

- ✅ 多账号管理
- ✅ 自动获取RSA加密公钥
- ✅ 自动生成加密参数
- ✅ 自动签到操作
- ✅ 自动抽奖功能（可自定义抽奖次数）
- ✅ 任务中心页面独立执行
- ✅ 天天领福利页面独立执行
- ✅ 打卡免费领会员
- ✅ 会员免费试用申请
- ✅ 天天抽奖
- ✅ 主入口统一执行多个页面任务
- ✅ 账号间随机延迟（5-10秒）
- ✅ 详细的签到奖励显示
- ✅ 每次抽奖结果展示
- ✅ 推送执行结果（支持Bark推送）

### 页面说明

- `任务中心`：执行原有的签到、积分查询和抽奖流程
- `天天领福利`：自动定位活动入口并执行 `打卡免费领会员`、`会员免费试用`、`天天抽奖`
- `main.py`：WPS 统一入口，按账号顺序依次执行 `任务中心` 和 `天天领福利`

## 目录结构

```text
wps/
├── api.py                # 任务中心 API 接口和加密模块
├── daily_benefits.py     # 天天领福利页面脚本
├── main.py               # WPS 统一入口
├── task_center.py        # 任务中心页面脚本
└── README.md             # 本文档
```

## 配置说明

### 1. 账号配置

在项目根目录的 `config/token.json` 文件中配置WPS账号信息：

```json
{
  "wps": {
    "accounts": [
      {
        "account_name": "默认账号",
        "user_id": 123456789,
        "cookies": "YOUR_WPS_COOKIES_HERE",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36",
        "max_lottery_limit": 5
      },
      {
        "account_name": "账号2",
        "user_id": 987654321,
        "cookies": "ANOTHER_WPS_COOKIES",
        "user_agent": "Mozilla/5.0 ..."
      }
    ]
  }
}
```

**配置参数说明：**

- `account_name`: 账号名称，用于日志和通知中识别账号
- `user_id`: **【必需】** WPS用户ID，从Cookie中的 `uid` 字段获取
- `cookies`: **【必需】** WPS登录Cookie
- `user_agent`: 【可选】用户代理字符串，不填则使用默认值
- `max_lottery_limit`: 【可选】最大抽奖次数限制，默认为2次。设置后将限制每次最多抽奖的次数，即使账户有更多抽奖机会

**⚠️ 重要提示：**
- `user_id` 是必需参数，如果配置中没有 `user_id`，该账号将被跳过，不执行签到
- `user_id` 可以从Cookie中的 `uid` 字段获取
- `max_lottery_limit` 用于控制抽奖次数，避免过度消耗抽奖机会。例如设置为5，则每次最多抽奖5次，即使账户有10次机会

### 2. 获取Cookies和User ID

#### 方法一：从用户中心页面获取 user_id（推荐）

**最简单的获取方式：**

1. 打开浏览器，访问 [WPS用户中心](https://personal-act.wps.cn/center_page/user_index)
2. 登录你的WPS账号
![img.png](img.png)
3. 会直接显示用户id


**或者：**
- 打开开发者工具 (F12)
- 切换到 **Application (应用)** 标签
- 左侧选择 **Cookies** → `https://personal-act.wps.cn`
- 在右侧Cookie列表中找到 `uid`，其值就是你的 `user_id`

#### 方法二：从接口请求获取（推荐用于获取完整Cookie）

**获取完整Cookie和user_id：**

1. 打开浏览器，访问 [WPS签到页面](https://personal-act.wps.cn/)
2. 登录你的WPS账号
3. 打开浏览器开发者工具 (F12)
4. 切换到 **Network (网络)** 标签
5. 在页面上执行一次签到操作
6. 在网络请求列表中找到签到相关的接口请求（如 `sign_in`、`encrypt/key` 等）
7. 点击该请求，查看 **Request Headers（请求头）**
8. 复制 `Cookie` 字段的完整内容

**提取 user_id：**

从复制的Cookie字符串中找到 `uid=数字` 部分，例如：

```
uid=655953169; wps_sid=V02S...; csrf=...
    ↑
  这就是 user_id
```

在这个例子中，`user_id` 就是 `655953169`

**为什么要从接口请求获取Cookie？**
- ✅ 接口请求的Cookie包含完整的认证信息（包括 `uid` 字段）
- ✅ 确保Cookie是有效且最新的
- ✅ 避免Cookie不完整导致签到失败
- ⚠️ 不要使用浏览器地址栏复制Cookie，可能缺少必要字段

**配置示例：**

假设从接口获取的Cookie为：
```
uid=655953169; wps_sid=V02Syi5I...; csrf=SCXAn6r5...
```

则在配置文件中填写：
```json
{
  "account_name": "我的账号",
  "user_id": 655953169,           // 从Cookie中的uid字段提取，或从用户中心页面获取
  "cookies": "uid=655953169; wps_sid=V02Syi5I...; csrf=SCXAn6r5...",  // 完整Cookie
  "user_agent": "Mozilla/5.0 ..."
}
```

**说明：**
- `user_id`: 从Cookie中的uid字段提取（655953169），或从用户中心页面获取
- `cookies`: 从接口请求中复制的完整Cookie字符串

### 3. 推送配置（可选）

如需启用推送通知，需要在 `config/notification.json` 中配置Bark推送参数，或在环境变量中配置：

```bash
export BARK_PUSH="YOUR_BARK_KEY"           # Bark推送密钥（必需）
export BARK_SOUND="birdsong"               # 推送声音（可选）
export BARK_GROUP="WPS签到"                # 推送分组（可选）
export BARK_LEVEL="active"                 # 推送级别（可选）
```

**推送通知内容包括：**
- 📊 总体统计（总账号数、成功数、失败数）
- 📋 每个账号的详细结果
  - `任务中心` 页面结果
  - `天天领福利` 页面结果
  - 页面内各功能模块的执行结果

## 使用方法

### 直接运行

```bash
cd /Users/cat/Projects/python/PrivateProjects/ZaiZaiCat-Checkin/script/wps
python main.py
```

### 单独运行任务中心

```bash
cd /Users/cat/Projects/python/PrivateProjects/ZaiZaiCat-Checkin/script/wps
python task_center.py
```

### 单独运行天天领福利

```bash
cd /Users/cat/Projects/python/PrivateProjects/ZaiZaiCat-Checkin/script/wps
python daily_benefits.py
```

### 定时任务

可以使用cron或青龙面板等工具设置定时执行：

```bash
# 每天早上9点执行
0 9 * * * cd /path/to/ZaiZaiCat-Checkin/script/wps && python main.py
```

## 依赖库

```bash
pip install requests pycryptodome
```

## 注意事项

1. **Cookie安全**
   - 请妥善保管你的Cookie信息
   - 不要分享给他人
   - 定期更新Cookie

2. **签到频率**
   - 建议每天执行一次
   - 避免频繁请求

3. **抽奖次数控制**
   - 可通过 `max_lottery_limit` 参数控制每次最多抽奖次数
   - 未设置时默认为2次
   - 避免过度消耗抽奖机会

4. **活动页面执行**
   - `main.py` 会按账号顺序依次执行 `任务中心` 和 `天天领福利`
   - 如只想执行其中一个页面，可直接运行对应的页面脚本
   - `天天领福利` 依赖官方页面活动参数，页面内容后续可能随官方活动更新

5. **账号间延迟**
   - 多账号时自动在账号间添加5-10秒随机延迟
   - 提高安全性，避免被检测为异常操作

6. **错误处理**
   - 脚本会自动处理网络错误和签到失败
   - Token过期时会提示重新登录
   - 如持续失败，请检查Cookie是否过期

7. **公钥更新**
   - 公钥会定期从服务器获取
   - 无需手动更新

## 更新日志

### v1.2 (2026-03-11)
- ✅ 将原有 WPS 功能拆分为 `任务中心` 独立页面脚本
- ✅ 新增 `天天领福利` 页面脚本
- ✅ 支持 `打卡免费领会员`
- ✅ 支持 `会员免费试用` 自动申请
- ✅ 支持 `天天抽奖`
- ✅ `main.py` 统一执行两个页面任务

### v1.1 (2025-12-18)
- ✅ 添加自动抽奖功能
- ✅ 支持自定义最大抽奖次数限制
- ✅ 添加签到奖励详细显示功能
- ✅ 添加每次抽奖结果展示
- ✅ 优化推送通知内容
- ✅ 改进错误处理机制

### v1.0 (2025-12-01)
- ✅ 重构代码结构，分离API和主逻辑
- ✅ 支持统一配置文件管理
- ✅ 支持多账号管理
- ✅ 自动获取RSA公钥
- ✅ 集成推送通知功能
- ✅ 完善日志输出
- ✅ 符合开发规范

## 问题反馈

如遇到问题，请检查：
1. Cookie是否有效
2. User ID是否正确配置
3. 网络连接是否正常
4. 依赖库是否正确安装
5. 配置文件格式是否正确
6. max_lottery_limit参数是否合理设置

## 免责声明

本脚本仅供学习交流使用，请勿用于商业用途。使用本脚本产生的任何问题，由使用者自行承担。
