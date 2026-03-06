# 大潮（新流程）

本模块目标：用“账号密码登录”的抓包流程，自动完成 **签到** 与 **阅读有礼**（含抽奖）。

## 配置

默认读取：`config/token.json`（配置节点：`dachao.accounts[]`）

字段说明（`dachao.accounts[]`）：
- `account_name`：账号名称
- `phone_number`：手机号
- `password_encrypted`：抓包得到的“加密密码字符串”（不是明文）
- `user_agent`：抓包 UA（vapp 与 aihoge 使用同一个；必填）
- `passport_cookies` / `vapp_cookies` / `aihoge_cookies`：可选，抓包 Cookie（不要提交到 git）
- `passport_signature_salt`：可选，若 passport 的 `X-SIGNATURE` 有盐值校验，可在此补齐
- `aihoge_signature_salt`：可选，若 `/api/memberhy/tm/signature` 的 `signature` 有盐值校验，可在此补齐
- `sign_lottery_id`：可选，若“签到抽奖”活动 id 无法自动发现，可手填（抓包的 lottery activity id）
- `redeem_member`：可选，抽到现金红包(type=3)时用于兑换的 member(JSON字符串，通常 source=wechat)
- `redeem_cookies`：可选，兑换红包时使用的 Cookie（抓包为 HYPERF_SESSION_ID=...），不填则复用 aihoge_cookies
- `redeem_user_agent`：可选，兑换红包时使用的 UA，不填则复用 user_agent

注意：当前实现对 `passport X-SIGNATURE` 与 `aihoge signature` 使用了“占位算法”，如服务端有严格校验，需要你把真实算法/盐值补齐（或者直接把抓包算法移植到代码中）。

## 运行

- 全部任务：`python3 script/dachao/main.py`
- 仅签到：`python3 script/dachao/main.py --mode sign`
- 仅阅读：`python3 script/dachao/main.py --mode read`
