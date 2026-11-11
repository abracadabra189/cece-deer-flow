# 外部用户系统接入（手机号开通 + 免密登录）

> 面向：需要把 DeerFlow 嵌进已有用户体系的平台方 / 运维。
> 对应实现：`backend/app/gateway/routers/external_users.py`、
> `backend/app/gateway/auth/external_provisioning.py`、
> `backend/app/gateway/auth/external_ticket.py`、
> `backend/packages/harness/deerflow/config/auth_config.py::ExternalUserAuthConfig`。
> HTTP 契约英文版：`backend/docs/API.md#external-user-provisioning`；
> 认证体系定位：`backend/docs/AUTH_DESIGN.md`。

---

## 1. 这个功能解决什么

已有用户体系里的人**不该在 DeerFlow 再注册一次**。外部后端拿着「手机号 + 用户名」调用一个接口：

- 手机号**已注册** → 直接返回该用户的识别 token；
- 手机号**未注册** → 立刻用手机号建号，再返回 token；
- 拿到的 token 可以把用户**直接送进已登录状态**的 DeerFlow 界面（浏览器无需再登录）。

DeerFlow 侧不校验密码、不发短信——**认证权完全归外部系统**，DeerFlow 只信任调用方出示的共享密钥。

---

## 2. 端到端流程

```
外部用户系统（后端）                     DeerFlow Gateway                    浏览器
──────────────────────                ──────────────────────              ──────────────
① POST /api/v1/auth/external/provision
   X-External-User-Key: <api_key>
   { "phone": "+8613800138000",
     "username": "张三",
     "next": "/workspace/chats" }
                        ──────────►  校验密钥（常量时间比较）
                                     规范化手机号（去分隔符 / NFKC）
                                     按 (provider_id, phone) 查 users
                                       ├─ 命中 → 复用该账号（created=false）
                                       └─ 未命中 → 建号：
                                            email = {phone}@{email_domain}
                                            oauth_provider = provider_id
                                            oauth_id = phone
                                            password_hash = NULL（无法密码登录）
                                     写 user_preferences.external_username
                                     签发：access_token（会话 JWT）
                                          login_ticket（一次性票据，默认 120s）
                    ◄──────────────  返回 user_id / access_token /
                                     login_ticket / login_url
② 把 login_url 交给浏览器（302 跳转或前端 window.location）
                                                    ─────────────────────►
                                     ③ GET /api/v1/auth/external/login?ticket=…
                                        验签 + 校验 purpose/exp
                                        按 jti 单次消费（重放即拒）
                                        查用户（不存在/被禁用 → 拒绝）
                                        下发 Cookie：access_token、
                                        deerflow_session_persistent、csrf_token
                                        302 → /auth/callback?next=/workspace/chats
                                                                            ④ 前端 callback
                                                                               页确认会话
                                                                               → 进入工作台
                                                                               （已登录）
```

失败路径统一收敛：票据缺失/伪造/过期/重放/账号被禁用 → `302 → /login?error=external_login_failed`，
**不下发任何 Cookie**，因此该端点无法被用来探测票据是否有效。

---

## 3. 实现说明

### 3.1 代码分布

| 文件 | 职责 |
|---|---|
| `config/auth_config.py::ExternalUserAuthConfig` | `auth.external_user` 配置模型 + 校验（启用必须有 ≥16 字符密钥，否则**配置加载直接失败**） |
| `app/gateway/auth/external_provisioning.py` | 手机号/用户名规范化、派生邮箱、角色解析、查号或建号（含并发竞争收敛、409 防抢占、403 禁用拦截） |
| `app/gateway/auth/external_ticket.py` | 一次性登录票据的签发与消费（签名、TTL、`jti` 校验；消费落库） |
| `persistence/external_login_tickets/`（harness） | 已消费票据的共享表与原子 claim（`INSERT … ON CONFLICT DO NOTHING` + 事务内清扫）；迁移 `0053_external_login_tickets` |
| `app/gateway/routers/external_users.py` | 两个 HTTP 端点、密钥校验、Cookie 下发、跳转构造、用户名落库 |
| `app/gateway/auth_middleware.py` | `/api/v1/auth/external/` 加入公开路径前缀（自带凭据，不用会话 Cookie） |
| `app/gateway/csrf_middleware.py` | `/api/v1/auth/external/provision` 加入 CSRF 豁免（机器调用没有双提交 Cookie 对） |
| `extensions/gateway.py` | 上面两份放行清单的**镜像常量**（harness 不能 import app，由 `tests/test_extension_gateway_wiring.py` 钉住一致性） |

### 3.2 身份映射（不加表结构）

复用既有的外部身份列，因此不需要数据库迁移：

| `users` 字段 | 取值 | 说明 |
|---|---|---|
| `oauth_provider` | `auth.external_user.provider_id`（默认 `external-phone`） | 多套外部系统用不同 provider_id 区分 |
| `oauth_id` | 规范化后的手机号 | **身份键**；与 provider 组成唯一偏索引 |
| `email` | `{phone}@{email_domain}`（去掉 `+`） | 列非空且唯一，手机号用户没有邮箱，故派生一个**保留域**地址；它只是存储键，不是收件地址 |
| `password_hash` | `NULL` | 该账号无法走密码登录，认证权在外部系统 |
| `system_role` | `default_role`（默认 `user`）；命中 `admin_phones` 则 `admin` | |
| `disabled` | 沿用平台账号禁用 | 禁用后开通返回 403、票据兑换直接拒绝 |

外部传入的**用户名**存在 `user_preferences.external_username`（每次调用刷新），不进 `users` 表。

并发安全：`(oauth_provider, oauth_id)` 的唯一偏索引保证同一手机号的并发开通收敛到同一行——
落败方 INSERT 抛 `ValueError`，代码改为重读并返回胜者，不会出现重复账号或 500。

防抢占：若派生邮箱已被**别的**账号占用（例如有人用同名邮箱本地注册过），返回 `409`，
绝不把外部身份挂到既有本地账号上——与 OIDC 开通的规则一致。

### 3.3 一次性票据（login_ticket）

- 用 `AUTH_JWT_SECRET` 签名（HS256），声明为 `purpose=external_user_login`、`uid`、`jti`、`iat`、`exp`、可选 `next_path`。
- **故意不带 `sub`**：会话 JWT 的解码模型 `TokenPayload` 要求 `sub`，所以票据即使泄漏也**无法**被当成 `access_token` 重放（解码结果为 MALFORMED）。反向同理：会话 JWT 也无法当票据用。
- 单次消费：兑换即向 `external_login_tickets` 表执行一次 `INSERT … ON CONFLICT (jti) DO NOTHING`，
  以受影响行数判定谁赢。`jti` 是主键，因此**多 worker、多副本共享同一数据库时对"已用过"达成一致**；
  过期行在同一事务内按批（200 行/次）清扫，表不会无限增长。
- 无法记录消费（无数据库、存储异常）时**拒绝票据**——fail closed，绝不退回进程内判定。
- TTL 默认 120 秒（可配 10–900）。票据会出现在浏览器地址栏，因此调用方应尽快跳转，不要长期保存或写日志。

### 3.4 会话与凭据边界（**对接必读**）

`login` 兑换成功后下发的是平台标准会话 Cookie：

| Cookie | 属性 |
|---|---|
| `access_token` | HttpOnly、SameSite=Lax；HTTPS 或 localhost 下持久化，公网 HTTP 下为会话级 |
| `deerflow_session_persistent` | HttpOnly，记住「持久会话」选择 |
| `csrf_token` | JS 可读，双提交 CSRF 用（前端自动带 `X-CSRF-Token`） |

**Gateway 只从 `access_token` Cookie 读取会话 JWT**，`Authorization: Bearer <jwt>` **不被接受**
（那个位置属于 `dfp_` 前缀的个人访问令牌 PAT）。因此：

- 浏览器接入 → 用 `login_url`（推荐，零前端改动）；
- WebView / 原生 App → 把返回的 `access_token` 写成名为 `access_token` 的 Cookie；
- 纯后端调 API → 需要 `Authorization` 头时，请让用户在界面里创建 PAT（`dfp_…`），
  注意 PAT 只覆盖 thread/run/project 等白名单路由，其余路由返回 403。

### 3.5 安全边界

| 风险 | 处置 |
|---|---|
| 密钥即「任意手机号的账号」 | 等同管理员凭据：只放 `.env`（`api_key: $EXTERNAL_USER_API_KEY`）、只在内网或 TLS 后暴露、轮换即改环境变量；启用而密钥缺失/短于 16 字符时**配置加载失败**，端点不可能裸奔 |
| 密钥被猜 | 常量时间比较；失败只回一句 `Invalid API key`（401），不区分「未启用/密钥错」，不构成 oracle；失败会记 WARNING（含来源 IP，不含手机号） |
| 票据被重放 | 单次消费 + 短 TTL + 失败统一跳转 |
| 票据当会话用 | 声明不含 `sub`，解码即 MALFORMED |
| 开放重定向 | `next` 走平台既有 `validate_next_param`（只允许相对路径，拒绝 `//`、绝对 URL、反斜杠、控制字符） |
| 手机号/用户名注入 | 手机号强校验 `^\+?[0-9]{5,20}$`；用户名 ≤100 字符且拒绝控制字符与双向格式字符（U+202A–202E、U+2066–2069 等）；派生邮箱经 JSON 转义写入 frontmatter 类字段的路径不复用，用户名只进 JSON 列 |
| CSRF | provision 豁免双提交（机器调用无 Cookie），但**没有**加入 `_AUTH_EXEMPT_PATHS`，因此不会触发 Origin 检查、也不会给机器调用下发 CSRF Cookie |
| 隐私 | 日志记 `user_id`/角色/是否新建，**不记手机号**；手机号只落在 `users.oauth_id` 与派生邮箱里 |

---

## 4. 接口使用说明

### 4.1 前置条件

1. `config.yaml` 打开开关（`.env` 提供密钥）：

```yaml
auth:
  external_user:
    enabled: true
    api_key: $EXTERNAL_USER_API_KEY     # 必填，≥16 字符
    provider_id: external-phone
    email_domain: users.deerflow.internal
    default_role: user
    admin_phones: []                    # 需要管理员权限的手机号
    ticket_ttl_seconds: 120
    session_expiry_minutes: null        # null = 跟随 JWT 默认（7 天）
    frontend_base_url: null             # null = 同源；跨域部署时填前端源
```

```dotenv
# .env（不进 git）
EXTERNAL_USER_API_KEY=<openssl rand -hex 32 之类的高熵值>
```

2. 重启 Gateway（改了 `.env` 必须**重建容器**，`env_file` 只在创建时读取）：

```bash
docker compose --env-file .env -p docker -f docker/docker-compose.yaml up -d --no-deps --force-recreate gateway
```

> `auth.external_user.*` 本身是热重载字段（每次请求实时读配置）；只有 `.env` 里的密钥变更需要重建容器。

### 4.2 开通 / 取 token

```
POST /api/v1/auth/external/provision
```

**请求头**

| Header | 必填 | 说明 |
|---|---|---|
| `X-External-User-Key` | 二选一 | 共享密钥 |
| `Authorization: Bearer <key>` | 二选一 | 同上，方便只有通用 HTTP 客户端的调用方 |
| `Content-Type` | 是 | `application/json`（含中文时用 `charset=utf-8` 并发送 UTF-8 字节） |

**请求体**

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `phone` | string | 是 | 身份键。5–20 位数字，可带前导 `+`；空格、`-`、`.`、`()` 会被剔除，全角数字自动归一 |
| `username` | string | 否 | 显示名，≤100 字符；每次调用刷新到 `external_username` 偏好 |
| `next` | string | 否 | 登录后落地的相对路径，例如 `/workspace/chats` |

**响应 200**

| 字段 | 说明 |
|---|---|
| `user_id` | DeerFlow 用户 UUID（后续排障、审计的主键） |
| `phone` | 规范化后的手机号 |
| `username` | 回显（未传则为 `null`） |
| `email` | 派生的保留域地址，例如 `8613800138000@users.deerflow.internal`；**不是邮箱**，不要发信 |
| `system_role` | `user` / `admin` |
| `created` | `true` 表示本次调用完成了注册；再次调用同一手机号为 `false` |
| `token_type` | 固定 `Bearer` |
| `access_token` | 会话 JWT。**只能作为 `access_token` Cookie 使用**（见 3.4） |
| `expires_in` | `access_token` 有效期（秒），默认 604800 |
| `login_ticket` | 一次性票据（已包含在 `login_url` 里，一般不用单独处理） |
| `login_url` | **交给浏览器**即可免密登录的完整 URL |

**curl 示例**

```bash
curl -sS -X POST http://localhost:2026/api/v1/auth/external/provision \
  -H "X-External-User-Key: $EXTERNAL_USER_API_KEY" \
  -H 'Content-Type: application/json; charset=utf-8' \
  -d '{"phone":"+8613800138000","username":"张三","next":"/workspace/chats"}'
```

**错误码**

| 状态码 | 含义 | 处理建议 |
|---|---|---|
| `401` | 密钥缺失或错误 | 检查 `.env` 与请求头；连续出现说明有人在探测 |
| `403` | 该账号被平台禁用 | 走管理员恢复，不要重复重试 |
| `404` | `auth.external_user.enabled` 为 false | 开关没开或配置没生效 |
| `409` | 派生邮箱已被无关账号占用 | 换 `email_domain`，或人工处理那条历史数据 |
| `422` | 手机号或用户名不合法 | 按上表规则修正 |

### 4.3 浏览器免密登录

```
GET /api/v1/auth/external/login?ticket=<login_ticket>&next=<可选>
```

- 直接把 `login_url` 交给浏览器（302 跳转、`window.location.href`、或新窗口打开均可）。
- 成功：下发三枚 Cookie 并 `302 → {frontend_base_url}/auth/callback?next=<目标路径>`，
  前端既有 callback 页确认会话后进入工作台，**无需改前端代码**。
- 失败：`302 → /login?error=external_login_failed`，不带 Cookie。
- `next` 优先级：查询参数 > 票据内 > `/workspace`；非法值被丢弃（防开放重定向）。
- 一个票据只能用一次；过期或重复使用都会走失败跳转，此时重新调用 provision 取新票据即可。

### 4.4 三种接入形态

| 形态 | 做法 | 适用 |
|---|---|---|
| **浏览器跳转（推荐）** | 外部系统 302 到 `login_url` | 门户/工作台里点「进入 DeerFlow」 |
| **WebView / 原生 App** | 调 provision，把 `access_token` 写成名为 `access_token` 的 Cookie（域指向 DeerFlow），再加载页面 | 嵌入式客户端 |
| **纯后端调 API** | provision 拿 `user_id`，界面里为该用户创建 PAT（`dfp_…`）后用 `Authorization: Bearer` | 服务端集成；注意 PAT 只覆盖 thread/run/project 白名单路由 |

### 4.5 外部系统对接清单

1. 向运维索取 `EXTERNAL_USER_API_KEY`，按管理员凭据保管（密钥库/环境变量，不落代码与前端）。
2. 只从**服务端**调用 provision，绝不在浏览器里带密钥。
3. 每次要放用户进来时**重新调用** provision 取新票据（幂等：同一手机号返回同一 `user_id`），不要缓存复用旧 `login_url`。
4. 拿到 `login_url` 后立即跳转；不要写日志、不要存库。
5. 记录返回的 `user_id`，便于后续排障与审计对齐。
6. 用户离职/停用时，在 DeerFlow 侧禁用账号（禁用后开通 403、票据兑换被拒），或在外部系统停止发起开通。

---

## 5. 配置项一览

| 字段 | 默认 | 说明 |
|---|---|---|
| `enabled` | `false` | 总开关；关闭时两个端点都 404 |
| `api_key` | `null` | 共享密钥，支持 `$ENV`；启用时必填且 ≥16 字符 |
| `provider_id` | `external-phone` | 写入 `users.oauth_provider`；hyphen-case，≤32 字符 |
| `email_domain` | `users.deerflow.internal` | 派生邮箱的保留域，必须是带点主机名；**不要**用真实收件域 |
| `default_role` | `user` | 新账号角色 |
| `admin_phones` | `[]` | 这些手机号开通为 `admin`（比较前先归一化） |
| `ticket_ttl_seconds` | `120` | 一次性票据有效期，允许 10–900 |
| `session_expiry_minutes` | `null` | 会话 JWT 有效期覆盖；`null` = 跟随 `token_expiry_days`（7 天） |
| `frontend_base_url` | `null` | 跨域部署时的前端源；`null` = 同源（走 nginx 即可） |

多套外部系统并存：每套一个 `provider_id` **且**一个独立 `email_domain`（否则同一手机号会撞同一个派生邮箱而 409）。

---

## 6. 本地实测记录（2026-07，端口 2026，经 nginx）

| 验证项 | 结果 |
|---|---|
| 新手机号开通 | `created=true`，返回 `user_id` / `access_token`(199B) / `login_ticket`(313B) / `login_url` |
| 同手机号再次开通 | 同一 `user_id`，`created=false`，票据不同 |
| 错误密钥 | `401` |
| 非法手机号 `12` | `422` |
| 含双向控制符的用户名 | `422` |
| 浏览器跟随 `login_url` | `302 → /auth/callback?next=/workspace/chats`，Cookie = `access_token, deerflow_session_persistent, csrf_token`，最终 `200 http://localhost:2026/workspace/chats`（真实前端页面） |
| 带 Cookie 调 `/api/v1/auth/me` | 返回同一 `user_id`，`role=user` |
| 票据重放 | `302 → /login?error=external_login_failed`，不发 Cookie |
| 伪造票据 | 同上 |
| `access_token` 直接当 Cookie 用 | `/api/v1/auth/me` 通过 |
| 落库核对 | `users`: `oauth_provider=external-phone`、`oauth_id=+86138000…`、`password_hash IS NULL`、`disabled=0`；`user_preferences.external_username="集成测试用户"`（UTF-8 正确） |

自动化测试：`backend/tests/test_external_user_auth.py`（配置校验 / 规范化 / 开通 / 票据 / HTTP 全链路）、
`backend/tests/test_external_login_ticket_store.py`（票据原子消费，SQLite 与 Postgres 双后端 + 真实多进程争用）、
`backend/tests/test_migration_0053_external_login_tickets.py`（迁移与 ORM 一致、升降级、部分应用补全），
另有 `backend/tests/blocking_io/test_auth_router_config_reads.py` 钉住两个新端点「配置读取必须离开事件循环」。

### 多 worker 评测（票据单次消费）

dev172（Postgres + Redis，`GATEWAY_WORKERS=2`，两个 uvicorn 进程 PID 12/13）实测：

| 验证项 | 结果 |
|---|---|
| 迁移在 Postgres 落地 | `deerflow.external_login_tickets` 建表，`pk_external_login_tickets`(jti) + `ix_external_login_tickets_expires_at` |
| 容器内跑票据仓储测试（真实 Postgres） | 26 passed（含 SQLite/Postgres 双后端与 3 进程争用同一 jti） |
| 容器内跑迁移测试（真实 Postgres） | 6 passed |
| **同一票据 20 并发兑换** | `granted=1 refused=19 other=0`，落库仅 1 行；即两个 worker 合计只放行一次 |

复现方式：容器内 `python /tmp/eval_ticket_concurrency.py <手机号> 20`（脚本经 nginx 前的
`127.0.0.1:8001` 直连网关，由 uvicorn 共享监听套接字把并发连接分散到各 worker）。
若把消费记录换回进程内缓存，同样的压测会得到 `granted=2`（每 worker 各一次）。

---

## 7. 已知边界

1. **票据单次消费依赖应用数据库**。`external_login_tickets` 表与 `users` 同库（迁移 `0053`），
   因此多 worker／多副本天然一致；若数据库不可用，票据一律被拒（fail closed），
   此时外部登录不可用，但不会出现重放窗口。
2. **返回的 JWT 不能当 `Authorization: Bearer` 用**。这是平台既有设计（该位置属于 PAT），
   本功能没有放宽它，以免扩大 CSRF 豁免面。
3. **用户名只是偏好项**，目前不参与界面展示逻辑；若要在 UI 显示，需要前端读取该偏好。
4. **没有手机号变更/合并流程**。手机号是身份键，改号等于新账号；需要迁移时走人工数据处理。
5. **没有限流**。端点由密钥保护，若担心密钥泄漏后的批量建号，可在网关/反向代理层加 IP 限流，
   或后续把平台的登录限流存储复用到该端点。
6. **派生邮箱占用唯一索引**。若历史上有人用 `{phone}@{email_domain}` 注册过本地账号，开通会 409，
   需要人工处理（改 `email_domain` 或清理该账号）。
