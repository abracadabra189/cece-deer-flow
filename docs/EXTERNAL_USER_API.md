# 外部用户系统对接接口说明

> **文档对象**：已有用户系统（以下称"接入方"）的开发人员
> **接口版本**：v1（`/api/v1/auth/external/*`）

---

## 1. 集成概览

接入方用**账户名（`account`）**为已有用户在 DeerFlow 侧换取登录态：已开通直接返回凭据，未开通立即建号后返回凭据。`account` 可以是中文、数字或邮箱，是唯一身份键；`phone` 选填，仅作联系信息。用户点击一个链接即进入已登录的 DeerFlow，无需二次注册、无需输入密码。

```
接入方后端                                DeerFlow Gateway                       用户浏览器
─────────────                            ─────────────────                      ────────────
① POST /api/v1/auth/external/provision
   X-External-User-Key: <API Key>
   {"account":"zhang.san",
    "phone":"+8613800138000",
    "username":"张三",
    "next":"/workspace/chats"}
                         ─────────────►   校验 API Key（恒定时间比较）
                                         account 归一化 → 查账号
                                           ├─ 已存在 → 复用（created=false）
                                           └─ 不存在 → 立即开通（created=true）
                                         签发 access_token + 一次性 login_ticket
                    ◄─────────────      200 {user_id, access_token, base_url,
                                              url_path, login_url, ...}

② 把 login_url 交给浏览器（302 或前端跳转）
                                                          ─────────────────►
                                         ③ GET /api/v1/auth/external/login?ticket=…
                                            验签 + 有效期 + 单次消费（落库，集群一致）
                                            下发会话 Cookie
                                            302 → /auth/callback?next=/workspace/chats
                                                                                ④ 落地即已登录
```

**关键约束（务必先读）**

| 约束 | 说明 |
|---|---|
| ① 只能服务端调用 | `provision` 携带 API Key，**绝不可**在浏览器、App 前端或任何用户可见位置调用 |
| ② API Key 等同管理员凭据 | 持有者可为**任意 account**取得账号。请存入密钥管理系统，按最高密级管理 |
| ③ `login_url` 一次性且短时 | 默认 120 秒内有效、只能兑换一次；**每次进入都要重新调用 `provision`**，不要缓存复用 |
| ④ `access_token` 不是 Bearer 令牌 | Gateway 只从名为 `access_token` 的 **Cookie** 读取会话；`Authorization: Bearer <access_token>` **不被接受**（该位置属于 `dfp_` 前缀的个人访问令牌 PAT） |
| ⑤ 不要记录票据 | `login_url` / `login_ticket` 会出现在浏览器地址栏，禁止写入日志、数据库、埋点 |

---

## 2. 前置准备

| 项目 | 说明 |
|---|---|
| Base URL | 由运维提供。形如 `https://<host>` 或 `http://<host>:<port>`；下文以 `{BASE}` 表示。当前已开启本接口的环境见下表 |
| API Key | 由运维在部署环境的 `.env` 中生成并线下交付（`X-External-User-Key` 使用）。**每套环境一把独立密钥** |
| 网络 | 接入方后端需能访问 `{BASE}`；建议走内网或 TLS。明文 HTTP 下会话 Cookie 不带 `Secure`，且公网 HTTP 场景下会话为浏览器会话级（关闭浏览器即失效） |
| 时钟 | 票据有效期依赖 Gateway 侧时钟，接入方无需同步；但 Gateway 多副本部署需 NTP |
| 编码 | 请求体使用 UTF-8；含中文时请设置 `Content-Type: application/json; charset=utf-8` 并按 UTF-8 编码字节 |

**当前环境**（正式对接地址以运维交付为准）：

| 环境 | Base URL | 说明 |
|---|---|---|
| 本地验证环境 | `http://localhost:2026` / `http://192.168.9.86:2026` | 单机验证、联调用；密钥变量 `EXTERNAL_USER_API_KEY` |
| CECE dev172 | `http://<dev172-host>:2027`（本机部署）；服务器部署默认端口 `2026` | 生产形态（PostgreSQL + 双 Worker）；密钥变量 `EXTERNAL_USER_API_KEY_DEV172`，与本地环境**不通用** |

---

## 3. 接口一：开通 / 换取凭据

```
POST {BASE}/api/v1/auth/external/provision
```

### 3.1 请求头

| Header | 必填 | 说明 |
|---|---|---|
| `X-External-User-Key` | 二选一 | API Key（推荐） |
| `Authorization` | 二选一 | `Bearer <API Key>`，便于只有通用 HTTP 客户端的场景 |
| `Content-Type` | 是 | `application/json`（含中文建议带 `; charset=utf-8`） |

> 密钥缺失或不正确返回同一个 `401`，响应体不区分具体原因（防止被用作密钥有效性探测）。

### 3.2 请求体

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `account` | string | **是** | 非空；≤128 字符；禁止控制字符与双向格式字符（U+202A–202E、U+2066–2069、U+200B、U+200E/200F、U+2028/2029、U+2060–2065、U+FEFF） | **身份主键**，即接入方账户系统里的账户名。可以是**中文**（`张三`）、**数字**（`13800138000`）或**邮箱**（`zhang.san@corp.com`）。归一化规则见附录 A |
| `phone` | string | 否 | 归一化后须匹配 `^\+?[0-9]{5,20}$` | 联系方式，仅作记录，**不参与身份判定**。允许空格、`-`、`.`、`()`（会被剔除）；全角数字自动转半角；前导 `+` 保留 |
| `username` | string | 否 | ≤100 字符；禁止控制字符与双向格式字符（同上） | 显示名。**不传则回退为 `account`**；每次调用都会刷新存储值 |
| `next` | string | 否 | 仅允许站内相对路径（以单个 `/` 开头）；`//`、绝对 URL、反斜杠、控制字符一律丢弃 | 登录后落地页。非法值**不报错**，按未传处理 |

> **身份判定只看 `account`**：同一 `account` 恒对应同一 DeerFlow 用户；同一 `phone` 配不同 `account` 会得到两个不同用户。若历史上用手机号作为身份开通过账号，把该手机号原样作为 `account` 传入即可命中原账号（见附录 A 的"手机号形态账户"规则）。

### 3.3 响应（HTTP 200）

新建与复用**都返回 200**，用 `created` 区分。

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | string(UUID) | DeerFlow 用户唯一标识。**建议接入方持久化**，用于后续排障与审计对齐 |
| `phone` | string \| null | 本次调用归一化后的手机号；请求未传 `phone` 时为 `null` |
| `username` | string \| null | 显示名回显：传了 `username` 用其值，否则等于 `account` |
| `email` | string | 平台内部派生的存储键（由 `account` 派生，规则见附录 B）。**不是真实邮箱，请勿向其发信**，也不要在接入方界面展示 |
| `system_role` | string | `user`（默认）或 `admin`（运维在 `admin_phones` 中预置的账户/手机号） |
| `created` | boolean | `true` = 本次调用完成了注册；`false` = 该 `account` 已存在，复用原账号 |
| `token_type` | string | 固定 `Bearer`（仅表示令牌形态，不代表可用 Authorization 头携带，见 §1 约束④） |
| `access_token` | string | 会话 JWT。作为名为 `access_token` 的 Cookie 使用；有效期见 `expires_in` |
| `expires_in` | integer | `access_token` 有效期（秒），默认 `604800`（7 天）。**浏览器会话同样使用这个时长**：通过 `login_url` 登录后拿到的会话令牌有效期与之一致 |
| `login_ticket` | string | 一次性登录票据原文（已内嵌在 `url_path` / `login_url` 中，通常无需单独使用） |
| `base_url` | string | 浏览器应使用的 Gateway 源，例如 `http://localhost:2026`（**不含**结尾斜杠）。运维配置了 `frontend_base_url` 时以它为准，否则取本次 `provision` 请求解析出的源——**若你的后端经内网地址调用本接口，请让运维配置 `frontend_base_url`，否则用户浏览器打不开 `login_url`** |
| `url_path` | string | 登录路径与查询串（含 `ticket`，以及可选的 `next`），相对于 `base_url`，例如 `/api/v1/auth/external/login?ticket=eyJ…&next=/workspace/chats` |
| `login_url` | string | `base_url + url_path` 的便捷拼接结果，**直接交给浏览器**即可免密登录 |

> 三个字段同时返回：只想跳转的用 `login_url`；需要换成自己的域名/反向代理前缀的，用 `base_url` 做替换基准、拼上 `url_path` 即可，无需对整条 URL 做字符串切割。`url_path` 中的 `next` 保持站内相对路径原样（`/` 不做百分号编码）。

### 3.4 请求 / 响应示例

```bash
curl -sS -X POST "{BASE}/api/v1/auth/external/provision" \
  -H "X-External-User-Key: $EXTERNAL_USER_API_KEY" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{"account":"zhang.san","phone":"+86 138-0000-5555","username":"文档示例用户","next":"/workspace/chats"}'
```

```json
{
  "user_id": "37bc3cbc-788d-4e2a-9bec-12bad34630a1",
  "phone": "+8613800005555",
  "username": "文档示例用户",
  "email": "zhang.san@users.deerflow.internal",
  "system_role": "user",
  "created": true,
  "token_type": "Bearer",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.…",
  "expires_in": 604800,
  "login_ticket": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.…",
  "base_url": "http://localhost:2026",
  "url_path": "/api/v1/auth/external/login?ticket=eyJhbGci…&next=/workspace/chats",
  "login_url": "http://localhost:2026/api/v1/auth/external/login?ticket=eyJhbGci…&next=/workspace/chats"
}
```

> `phone` 回显的是**归一化后**的值（示例中去掉了空格与连字符）；未传 `phone` 时该字段为 `null`。
> `email` 由 `account` 派生：ASCII 安全账户保留可读局部段（示例中的 `zhang.san`），中文或邮箱形态的账户则为稳定哈希（形如 `u3f2a…`，见附录 B）。

**最小请求**（只给必填项）：

```bash
curl -sS -X POST "{BASE}/api/v1/auth/external/provision" \
  -H "X-External-User-Key: $EXTERNAL_USER_API_KEY" \
  -H "Content-Type: application/json; charset=utf-8" \
  -d '{"account":"张三"}'
```

此时 `username` 回显为 `张三`（回退到 `account`），`phone` 为 `null`，`email` 为哈希形态。

### 3.5 错误响应（均为真实采集）

| HTTP | 响应体 | 触发条件 | 接入方处置 |
|---|---|---|---|
| `401` | `{"detail":"Invalid API key"}` | 密钥缺失、错误或为空 | 检查密钥配置；连续出现说明泄露或配错，联系运维轮换 |
| `404` | `{"detail":"External user provisioning is not enabled"}` | 该环境未开启此能力 | 联系运维开启（功能未开启时端点表现为"不存在"） |
| `403` | `{"detail":"This account has been disabled. Please contact your administrator."}` | 该 `account` 对应账号已被平台禁用 | 不要重试；引导用户联系管理员 |
| `409` | `{"detail":"An unrelated account already owns the derived email for this account name."}` | 派生邮箱已被无关账号占用（历史数据冲突） | 提交给平台运维处理；平台**不会**把外部身份挂到既有账号上 |
| `422` | `{"detail":[{"type":"missing","loc":["body","account"],"msg":"Field required","input":{…}}]}` | 缺少必填的 `account`（框架标准结构，`detail` 为数组） | 补上 `account` |
| `422` | `{"detail":"account must be a non-empty string"}` | `account` 缺失、为空、为空白或类型不是字符串 | 修正后重试 |
| `422` | `{"detail":"account must not contain control or bidirectional formatting characters"}` | `account` 含控制/双向格式字符 | 清洗后重试 |
| `422` | `{"detail":"account must be at most 128 characters"}` | `account` 超长 | 改用更短的账户标识 |
| `422` | `{"detail":"phone must be 5-20 digits with an optional leading +"}` | 传了 `phone` 但格式非法 | 修正后重试（或省略该字段） |
| `422` | `{"detail":"phone must be a string"}` / `{"detail":"username must be a string"}` | 字段类型错误 | 修正后重试 |
| `422` | `{"detail":"username must not contain control or bidirectional formatting characters"}` | 用户名含控制/双向字符 | 清洗后重试 |
| `422` | `{"detail":"username must be at most 100 characters"}` | 用户名超长 | 截断或改用短名 |

### 3.6 幂等与并发语义

- **幂等**：同一 `account` 重复调用返回**同一** `user_id`，`created` 从 `true` 变为 `false`；每次调用都会签发**新的** `access_token` 与 `login_ticket`（旧票据不受影响，直到其自然过期）。
- **归一化后幂等**：`Zhang.San` / `zhang.san` / `  zhang.san  ` 视为同一账户；手机号形态的 `+86 138-0000-5555` 与 `+8613800005555` 也视为同一账户（附录 A）。
- **并发安全**：同一 `account` 并发开通由数据库唯一约束收敛为**一个账号**，落败方自动读取胜出方结果返回，不会报错、不会产生重复账号。
- **无内建限流**：该端点由 API Key 保护、不做频率限制。请接入方自行控制调用频率（建议仅在用户实际点击进入时调用，不要批量预开通）。

---

## 4. 接口二：浏览器免密登录

```
GET {BASE}/api/v1/auth/external/login?ticket=<login_ticket>&next=<可选>
```

由**浏览器**访问（302 跳转、`window.location.href`、新窗口打开均可），不需要也不应该携带 API Key。

### 4.1 参数

| 参数 | 必填 | 说明 |
|---|---|---|
| `ticket` | 是 | `provision` 返回的 `login_ticket`（`login_url` 已带好） |
| `next` | 否 | 覆盖票据内的落地页；校验规则同 §3.2，非法值丢弃 |

`next` 优先级：**查询参数 > 票据内携带 > 默认 `/workspace`**。

### 4.2 成功响应（真实采集）

```http
HTTP/1.1 302 Found
location: /auth/callback?next=/workspace/chats
set-cookie: access_token=<JWT>; HttpOnly; Max-Age=604800; Path=/; SameSite=lax
set-cookie: deerflow_session_persistent=1; HttpOnly; Max-Age=604800; Path=/; SameSite=lax
set-cookie: csrf_token=<TOKEN>; Max-Age=604800; Path=/; SameSite=strict
x-trace-id: a0f0d22567ec4f04b2df76284f00fee2
```

| Cookie | 属性 | 用途 |
|---|---|---|
| `access_token` | HttpOnly、SameSite=lax、Path=/ | 会话凭证（HTTPS 下追加 `Secure`） |
| `deerflow_session_persistent` | HttpOnly、SameSite=lax | 记住"持久会话"选择 |
| `csrf_token` | JS 可读、SameSite=strict | 前端发起写操作时自动回填 `X-CSRF-Token` |

跳转目标 `/auth/callback` 是 DeerFlow 前端既有页面，它会校验会话后自动跳到 `next`。**接入方无需实现任何回调页面。**

### 4.3 失败响应

所有失败一律 `302` 到 `/login?error=external_login_failed`，**且不下发任何 Cookie**：

```http
HTTP/1.1 302 Found
location: /login?error=external_login_failed
```

失败原因（对外不区分，避免成为票据有效性探测入口）：票据缺失 / 格式错误 / 签名不符 / 已过期 / **已被使用** / 账号不存在 / 账号被禁用 / 该环境未开启此能力。

### 4.4 票据语义

| 特性 | 说明 |
|---|---|
| 有效期 | 默认 **120 秒**（平台可配 10–900 秒） |
| 单次使用 | 消费记录写入数据库并做原子占用，**多进程 / 多副本集群内全局只放行一次**（实测 2 Worker、同票据 30 并发 → 放行 1 次、拒绝 29 次） |
| 不可当会话令牌 | 票据声明结构与会话 JWT 刻意不兼容，泄露也无法冒充登录态 |
| 过期后 | 直接失效；重新调用 `provision` 取新票据即可 |

---

## 5. 三种接入形态

| 形态 | 做法 | 适用场景 |
|---|---|---|
| **浏览器跳转（推荐）** | 用户点击"进入 DeerFlow" → 接入方后端调 `provision` → 302 到 `login_url` | 门户、工作台、企业内网系统 |
| **WebView / 原生 App** | 调 `provision` → 把 `access_token` 写入 WebView Cookie（名称必须为 `access_token`，Domain 指向 DeerFlow 站点，Path=/）→ 加载页面 | 嵌入式客户端 |
| **纯后端调用 API** | `provision` 取 `user_id`；由该用户在 DeerFlow 界面创建 PAT（`dfp_…`），后端用 `Authorization: Bearer dfp_…` 调用 | 服务端集成。注意 PAT 仅覆盖 `threads` / `runs` / `projects`（含项目文档、回收站）白名单路由，其余路由一律 403 |

WebView 注入示例（Android）：

```java
CookieManager.getInstance().setCookie(
    "https://<host>",
    "access_token=" + accessToken + "; Path=/; Secure; SameSite=Lax");
```

> Cookie 名称必须是 `access_token`，Path 必须是 `/`；HTTPS 站点请加 `Secure`。注入后直接加载 `{BASE}/workspace` 即为已登录状态。

---

## 6. 账号与数据约定

| 项目 | 约定 |
|---|---|
| 身份主键 | 归一化后的 `account`（见附录 A）。**换 account 等于新账号**，平台不提供账户改名/合并流程 |
| 手机号 | 选填的联系信息，存为用户偏好项（键 `external_phone`），**不参与身份判定**；同一手机号配不同 `account` 会得到不同用户 |
| 密码 | 通过本接口开通的账号**没有密码**，无法使用 DeerFlow 登录页的密码登录；认证权完全归接入方 |
| 显示名 | `username`（缺省回退为 `account`）存为用户偏好项（键 `external_username`），每次调用刷新 |
| 账户名留档 | `account` 的原始形态（保留大小写）存为用户偏好项（键 `external_account`） |
| 角色 | 默认 `user`；运维可通过配置项把指定账户或手机号设为 `admin` |
| 停用 | 平台侧可禁用账号；禁用后 `provision` 返回 `403`、票据兑换失败 |
| 数据隔离 | 每个用户的会话、文件、记忆、技能按 `user_id` 隔离 |

---

## 7. 联调自测清单

按顺序执行，全部通过即可上线：

- [ ] `provision` 带正确 Key → `200`，`created=true`，拿到 `user_id` / `access_token` / `base_url` / `url_path` / `login_url`
- [ ] 校验 `base_url + url_path == login_url`；把 `base_url` 换成你自己的入口域名后，`url_path` 仍能正常兑换（反向代理场景必测）
- [ ] 同一 `account` 再调一次 → `200`，`created=false`，`user_id` 与上次**相同**
- [ ] 同一账户的不同写法（`Zhang.San` / `zhang.san` / `  zhang.san  `）→ 同一 `user_id`
- [ ] 三种 `account` 形态各测一次：中文（`张三`）、数字（`13800138000`）、邮箱（`zhang.san@corp.com`）→ 均 `200`，且中文/邮箱形态的 `email` 为 `u` 开头的哈希形态
- [ ] 只传 `account`（不传 `phone`/`username`）→ `200`，`phone` 为 `null`，`username` 等于 `account`
- [ ] 错误 Key → `401`；缺 Key → `401`（两者响应体一致）
- [ ] 缺 `account` 字段 → `422`（`detail` 为数组）；`account` 为空白串 → `422`
- [ ] 传了非法 `phone`（如 `12`）→ `422`
- [ ] 浏览器打开 `login_url` → 落到 `/workspace/chats`（或指定 `next`），界面显示为已登录
- [ ] 用同一 `login_url` 再打开一次 → 跳到登录页并提示失败（票据已消费）
- [ ] 等待超过票据有效期后打开 → 同上失败
- [ ] `provision` 的 `next` 传 `//evil.example` → 返回的 `login_url` **不含** `next`，兑换后落地 `/auth/callback?next=/workspace`，不会跳到外部站点（实测行为）
- [ ] `login` 查询参数 `next` 传非法值 → 丢弃该值，改用票据内的 `next`（若票据也没有则 `/workspace`）
- [ ] 携带 Cookie 调 `GET {BASE}/api/v1/auth/me` → 返回的 `id` 与 `user_id` 一致
- [ ] （可选）并发压测：同一票据 N 个并发请求 → 仅 1 个成功

自测脚本（bash，需先 `export BASE=… KEY=…`）：

```bash
R=$(curl -sS -X POST "$BASE/api/v1/auth/external/provision" \
      -H "X-External-User-Key: $KEY" -H 'Content-Type: application/json; charset=utf-8' \
      -d '{"account":"liandong-user","username":"联调用户"}')
echo "$R"
URL=$(echo "$R" | python3 -c 'import json,sys; print(json.load(sys.stdin)["login_url"])')
curl -sS -i -o /dev/null -w 'first  -> %{http_code} %{redirect_url}\n' "$URL"
curl -sS -i -o /dev/null -w 'replay -> %{http_code} %{redirect_url}\n' "$URL"
```

期望输出：`first -> 302 …/auth/callback?next=/workspace`，`replay -> 302 …/login?error=external_login_failed`。

---

## 8. 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 一直 `401` | Key 复制含空格/换行；或用错了另一套环境的 Key | 逐字符核对；确认环境对应关系（每套环境独立密钥） |
| `404` | 该环境未开启外部对接 | 联系运维开启 |
| 跳转后回到登录页 | 票据过期（>120 秒）或已被使用；或浏览器禁用了 Cookie | 重新调 `provision` 取新 `login_url`，且**不要**在跳转前预取/缓存 |
| 跳转成功但页面显示未登录 | 浏览器阻止第三方 Cookie（跨域嵌入 iframe 场景） | 用整页跳转而非 iframe；或同域部署 |
| `access_token` 放进 `Authorization` 头返回 401 | 设计如此：该头只接受 PAT（`dfp_` 前缀） | 改用 Cookie（浏览器/WebView），或让用户创建 PAT（后端调用） |
| `409` | 派生邮箱与既有账号冲突（历史数据） | 提交平台运维处理，不要重试 |
| 登录后 7 小时/次日掉线 | 会话有效期到期（默认 7 天，平台可配） | 重新走一次 `provision` + `login_url` |

---

## 9. 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11 | v1.2 | **不兼容变更**：新增必填入参 `account`（账户系统名称，支持中文/数字/邮箱）作为身份主键；`phone` 降为选填、仅作联系信息；`username` 缺省时回退为 `account`；响应 `phone` 变为可空（`null`）。出参字段集合不变。历史手机号账号仍可通过"把手机号作为 `account` 传入"命中 |
| 2026-11 | v1.1 | `provision` 响应新增 `base_url` 与 `url_path`（`login_url` 保留，等于两者拼接），便于经自有域名/反向代理进入时直接换基准，无需切割整条 URL |
| 2026-11 | v1 | 首次发布：`provision` + `login` 两个端点；票据单次消费由进程内缓存改为数据库原子占用，支持多 Worker / 多副本横向扩容 |

---

## 附录 A：`account` 归一化规则（身份主键）

平台区分两种形态：**显示形态**（回显与留档，保留原大小写）与**身份形态**（写入唯一索引，用于判定"是不是同一个账户"）。

**显示形态**
1. Unicode NFKC 归一（全角数字/兼容字符 → 半角标准形）
2. 去除首尾空白
3. 拒绝空值、控制字符与双向格式字符、超过 128 字符 → `422`

**身份形态**（在显示形态基础上）
- **手机号形态优先**：若剔除空格、`-`、`.`、`(`、`)` 后匹配 `^\+?[0-9]{5,20}$`，则按手机号规则归一，保留前导 `+`
  - `+86 138-0013-8000`、`(+86) 138 0013 8000`、`+8613800138000` → 同一身份 `+8613800138000`
  - `１３８００１３８０００`（全角）→ `13800138000`
  - 这条规则保证**历史上以手机号开通的账号**在改为传 `account` 后仍能被命中
- **其他形态**：连续空白折叠为单个空格 + 大小写折叠（casefold）
  - `Zhang.San`、`zhang.san`、`  ZHANG.SAN  ` → 同一身份 `zhang.san`
  - `Zhang.San@Corp.com` → `zhang.san@corp.com`
  - `张三` → `张三`（中日韩文字无大小写，原样保留）

> 大小写折叠是刻意的：账户名与邮箱在实践中不区分大小写，不折叠会让同一个人因大小写差异产生两个账号、两份数据。若接入方的账户系统确实区分大小写，请在对接前与平台方确认。

**`phone` 字段**（选填，仅联系信息）：NFKC → 剔除空格/`-`/`.`/`(`/`)` → 校验 `^\+?[0-9]{5,20}$`，不匹配则 `422`；不传或传空白串视为未提供。

## 附录 B：派生邮箱规则

`users.email` 列非空、唯一且需是合法邮箱格式，而外部账户名可能是中文或另一个域的邮箱，因此平台按**身份形态**派生一个保留域地址：

| `account` 身份形态 | 派生规则 | 示例 |
|---|---|---|
| ASCII 且符合邮箱局部段字符集（字母/数字开头，仅含 `A-Za-z0-9._+-`，≤64 字符） | 直接作为局部段（去掉前导 `+`） | `zhang.san` → `zhang.san@users.deerflow.internal`<br>`+8613800005555` → `8613800005555@users.deerflow.internal` |
| 其他（中文、含 `@` 的邮箱、含其他符号、超长） | `u` + 身份形态的 SHA-256 前 24 位十六进制 | `张三` → `u3f2a9c…@users.deerflow.internal`<br>`zhang.san@corp.com` → `u81b4d0…@users.deerflow.internal` |

要点：

- 派生是**确定性**的：同一账户永远得到同一地址，因此唯一索引能正常发挥幂等作用。
- 邮箱形态的 `account` **不会**被直接当作 `users.email` 使用——否则会与平台上真实使用该邮箱的本地/OIDC 账号冲突；哈希派生把外部命名空间与真实邮箱命名空间隔开。
- 该地址**仅作为存储键**：不可投递、不应展示给用户、不应作为接入方的用户标识（请统一使用 `user_id`，或接入方自己的 `account`）。
