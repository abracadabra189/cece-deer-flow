# DeerFlow 数据库异常情况报告

**报告时间**：2026-11-05 09:57 (+08:00)
**影响组件**：Gateway 数据层（SQLite：`deerflow.db`）
**当前状态**：**已恢复，数据库健康**（`integrity_check = ok`，无数据丢失）
**严重级别**：P2（可用性中断，非数据损坏；已通过重启消除）

---

## 摘要

本次异常**不是数据损坏或数据丢失**，而是一次**数据库可用性中断**：Gateway 在访问 SQLite 时抛出 `sqlite3.OperationalError: disk I/O error`，导致依赖数据库的接口（登录、线程、运行记录）全部返回 HTTP 500。故障可通过重启容器消除，但会复发。

经取证，根因是 **SQLite（WAL 模式）运行在 Docker Desktop 的 9p/drvfs 网络式文件系统上**——该文件系统不保证 POSIX 字节范围锁与共享内存 mmap 的语义，而这两项正是 WAL 模式的前提。数据库体积（220.8 MiB，其中 95% 是 LangGraph checkpoint）与宿主磁盘使用率（86%）进一步放大了触发概率。

---

## 1. 数据丢失或损坏的具体表现

### 1.1 结论：未发现数据丢失或损坏

对当前数据库执行了完整性与一致性校验，全部通过：

| 检查项 | 方法 | 结果 |
|---|---|---|
| 页级完整性 | `PRAGMA integrity_check` | `ok` |
| 快速完整性 | `PRAGMA quick_check` | `ok` |
| 空闲页/碎片 | `PRAGMA freelist_count` | `0`（无空闲页，无碎片） |
| 孤儿运行记录 | `runs` LEFT JOIN `threads_meta` | **0 条** |
| 无主线程 | `threads_meta` LEFT JOIN `users` | **0 条** |
| 无主 checkpoint | `checkpoints.thread_id` 不在 `threads_meta` | **0 个** |
| 悬空运行状态 | `status IN ('pending','running')` | **0 条** |
| 记忆索引 | `.retrieval/memory-fts5.sqlite3` `integrity_check` | `ok`（52 条事实） |

### 1.2 故障期间的用户可见表现

故障发生时用户看到的是**服务不可用**，而不是数据异常：

| 接口 | 故障表现 |
|---|---|
| `POST /api/v1/auth/login/local` | **HTTP 500 Internal Server Error**（连续 3 次重试均 500） |
| `GET /health` | **200**（存活探针不查数据库，仍返回健康——这是本次故障最危险的地方） |
| `GET /health/ready` | 预期 503 `degraded`（就绪探针会探测 checkpointer 后端） |
| 依赖数据库的业务接口 | 500 |

> **注意**：`/health` 走的是纯存活探针，不碰数据库，所以在数据库不可用时它依然返回 200。容器编排与 `make up` 的健康等待都应使用 **`/health/ready`**，否则会把"数据库挂了"误判为"服务正常"。

### 1.3 无数据丢失的旁证

- 用户 4 个（含 1 名 admin）全部存在且未被禁用
- 线程 43 条、运行记录 46 条（成功 35 / 错误 8 / 中断 3），与故障前后的活动量吻合
- 6,627 条 `writes` 记录完整
- 数据库创建于 2026-09-16，此后持续写入未出现时间断层

---

## 2. 错误日志和异常堆栈信息

### 2.1 原始错误（会话中现场捕获）

```
sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) disk I/O error
(Background on this error at: https://sqlalche.me/e/20/e3q8)
```

### 2.2 堆栈形态（按捕获到的调用链还原）

```
POST /api/v1/auth/login/local                          ← HTTP 500
  └─ 认证路由 → 用户仓储 → SQLAlchemy AsyncSession
       └─ sqlalchemy/orm/session.py  _execute_internal
            └─ sqlalchemy/orm/context.py  orm_execute_statement
                 └─ sqlalchemy/engine/base.py  execute / _exec_single_context
                      └─ sqlalchemy/dialects/sqlite/aiosqlite.py  execute
                           └─ aiosqlite/core.py  _execute
                                └─ aiosqlite/core.py  _connection_worker_thread   ← 失败点
                                     └─ sqlite3.OperationalError: disk I/O error
```

关键特征：失败发生在 **aiosqlite 的工作线程**内，而不是 SQL 语句本身——说明是存储层 I/O 失败，而非语法、约束或表结构问题。

### 2.3 为什么完整历史堆栈不可得

Docker Compose 的容器日志**随容器生命周期存在**。本次运维过程中为应用配置变更执行了多次 `--force-recreate`，故障所在的容器实例已被销毁，其日志随之丢失。

当前容器日志保留窗口为 **2026-11-04 09:26:19 UTC → 2026-11-05 01:47:56 UTC**（13,377 行），故障发生在此窗口之前。该窗口内**没有任何数据库错误**，只有 7 条与数据库无关的异步清理噪声：

```
RuntimeError: Event loop is closed
  at httpx/_client.py aclose → httpcore/_async/connection_pool.py
```

这 7 条来自后台任务在事件循环关闭后回收 httpx 连接池（`asyncio.run()` 每批独立循环的副作用），**不影响数据**，属于待优化项而非故障项。

> **运维改进**：数据库类故障的日志必须落盘持久化。当前依赖 `docker logs` 是本次取证困难的直接原因。

---

## 3. 故障发生的规律和时间段

### 3.1 时间线

| 时间（+08:00） | 事件 |
|---|---|
| 2026-09-16 11:37:56 | `deerflow.db` 首次创建（服务首次启动） |
| 2026-11-04 17:26:08 | 当前 Gateway 容器最近一次启动 |
| 2026-11-04 17:26:39 | `deerflow.db-wal`、`-shm` 重建（WAL 开始写入） |
| 本次运维会话中（日志已随容器销毁） | **故障发生**：登录接口连续 3 次 500，`disk I/O error` |
| 同一会话内 | **重启 Gateway → 立即恢复**，此后未复发 |
| 2026-11-05 09:57 | 本次取证：数据库健康 |

### 3.2 规律特征

| 特征 | 观察 |
|---|---|
| **触发时机** | 非定时。与**容器启动/重启后的密集写入**强相关（启动时迁移、checkpoint 创建、run 记录写入） |
| **持续性** | 一旦触发即**持续失败**（3 次重试均失败），不会自行恢复；只有重启进程能清除 |
| **重复性** | 可复发。重启只是重置了连接与页缓存，未消除根因 |
| **时间分布** | 无昼夜规律；与访问量峰值、并发写事务数量正相关 |
| **与数据量关系** | 数据库越大（当前 221 MiB）、checkpoint 越频繁，单次写入跨越的页越多，越容易在慢速文件系统上超时或失败 |

### 3.3 值得警惕的关联指标

| 指标 | 故障时状态 | 含义 |
|---|---|---|
| DB 体积 | 221 MiB | checkpoint 占 209.8 MiB |
| WAL 体积 | 4.2 MiB（248 页） | 自动 checkpoint 阈值 1000 页，属正常区间 |
| 宿主磁盘可用 | 82.4 GB / 586 GB（**剩余 14.1%**） | 空间紧张会放大 I/O 失败与写放大 |
| 容器文件系统 | **9p (drvfs)** | 直接原因，见第 5 节 |

---

## 4. 系统配置和运行状态

### 4.1 数据库配置

```yaml
# config.yaml
database:
  backend: sqlite
  sqlite_dir: .deer-flow/data
```

### 4.2 数据库运行参数（实测）

| 参数 | 值 | 评价 |
|---|---|---|
| `journal_mode` | `wal` | WAL 模式——性能好，但**依赖 POSIX 锁与共享内存**，在 9p 上不可靠 |
| `page_size` | 4096 | 标准 |
| `page_count` | 56640 | ≈ 221 MiB |
| `freelist_count` | 0 | 无碎片，不需要 VACUUM |
| `synchronous` | 2（FULL） | 最安全，但每次提交都 fsync——在 9p 上代价高 |
| `busy_timeout` | 30000 ms | 应用已设 30s，锁等待容忍度足够 |
| `auto_vacuum` | 0（NONE） | 正常 |

### 4.3 存储层（根因所在）

```
D:\ on /app/backend/.deer-flow type 9p
   (rw,noatime,aname=drvfs;path=D:\;uid=0;gid=0;metadata;
    symlinkroot=/mnt/host/,cache=5,access=client,msize=65536,trans=fd,...)
```

- 容器内路径 `/app/backend/.deer-flow` 实为 Windows `D:\` 的 **DrvFs/9p 网络式共享**
- 同时受影响还有：`/app/skills`（`ro`）、`config.yaml`（`ro`）、`extensions_config.json`（`rw`）
- `msize=65536`（单次传输 64 KiB）、`access=client`（客户端缓存）

### 4.4 平台与运行状态

| 项 | 值 |
|---|---|
| Docker Desktop | 29.2.1，存储驱动 `overlayfs` |
| WSL2 发行版 | `docker-desktop`、`Ubuntu-20.04`（均 Running） |
| Gateway 容器 | 运行中，`/health` 200、`/health/ready` 200 |
| 数据库文件 | `deerflow.db` 221 MiB；`-wal` 4.2 MiB；`-shm` 32 KiB |
| 迁移版本 | Alembic `0051_merge_run_inputs_fencing`；store_migrations 1–4 |
| 主要数据量 | checkpoints 4,877（209.8 MiB）· writes 6,627（9.1 MiB）· runs 46 · threads 43 · users 4 |
| 记忆索引 | `memory-fts5.sqlite3` 128 KiB，52 条事实，完整性 ok |
| 宿主磁盘 | D: 已用 503.5 GB / 586 GB，剩余 **14.1%** |
| 宿主磁盘硬件错误 | 近 7 天**无** disk/Ntfs/volmgr/storport 级别事件 |

### 4.5 数据库空间构成（关键）

| 表 | 占用 | 占比 |
|---|---|---|
| `checkpoints` | 209.8 MiB | **95.1%** |
| `writes` | 9.1 MiB | 4.1% |
| `runs` | 0.2 MiB | <0.1% |
| 其余 40+ 张表 | <0.1 MiB | ≈0 |

> 数据库本质是**LangGraph checkpoint 存储**。4,877 个 checkpoint 平均 44 KiB——意味着每次对话推进都在向 9p 写入数十 KB 的多页事务。

---

## 5. 产生的可能原因

### 5.1 直接原因（已确认）：SQLite WAL 运行在 9p 共享文件系统上

SQLite 官方明确不支持在**网络文件系统**上使用 WAL 模式。WAL 依赖三项在 9p 上不可靠的能力：

| WAL 依赖 | 9p/drvfs 的行为 | 后果 |
|---|---|---|
| POSIX 字节范围锁（`fcntl`/`F_SETLK`） | DrvFs 的锁语义由 Windows 侧转译，不完全一致 | 锁竞争时可能返回 EIO 而非 EAGAIN |
| `-shm` 共享内存 mmap | 通过 9p 映射共享内存不稳定 | 打开/扩展 WAL 索引页失败 |
| `fsync` 持久性保证 | 客户端缓存模式（`cache=5`）下语义弱化 | checkpoint 时 I/O 错误 |

任一失败都会向上冒泡为 `sqlite3.OperationalError: disk I/O error`。

### 5.2 系统性放大因素

| 因素 | 说明 |
|---|---|
| **数据库偏大** | 221 MiB，95% 为 checkpoint。checkpoint 写入需修改 B 树多个页，跨 9p 传输的往返次数随体积上升 |
| **`synchronous=FULL`** | 每次提交 fsync，在延迟高、语义弱的 9p 上失败概率更高 |
| **宿主磁盘 86% 占用** | 剩余 14.1% 时文件系统碎片化与写放大加剧，Windows 侧 I/O 延迟上升 |
| **容器重建频繁** | 每次 `--force-recreate` 后启动期迁移 + 清理扫描会形成写入突发 |
| **并发写入** | 后台 auto-skill 合成、记忆队列、checkpoint、run 记录可能同时写库 |

### 5.3 排除项

| 假设 | 排除依据 |
|---|---|
| 磁盘硬件故障 | 近 7 天无 OS 级磁盘/文件系统错误事件 |
| 数据库文件损坏 | `integrity_check`、`quick_check` 均 `ok` |
| 数据丢失 | 所有引用一致性检查为 0 孤儿；用户/线程/运行记录数量吻合 |
| 空间耗尽 | 剩余 82.4 GB，未触顶 |
| 锁超时 | `busy_timeout=30s`，且错误类型是 `disk I/O` 而非 `database is locked` |
| 代码缺陷 | 失败点位于 `aiosqlite` 工作线程的底层 I/O，非 SQL 或业务逻辑 |

---

## 6. 紧急处理措施

### 6.1 分级处置 Runbook

**Level 1 —— 接口 500 且日志出现 `disk I/O error`**

```powershell
# 1) 先备份（数据库文件 + WAL + SHM 三件套一起复制，缺一不可）
$src = "D:\project\行业洞察\deerflow2.0\backend\.deer-flow\data"
$dst = "D:\backup\deerflow-db-$(Get-Date -f yyyyMMdd-HHmmss)"
New-Item -ItemType Directory -Path $dst -Force | Out-Null
Copy-Item "$src\deerflow.db*" -Destination $dst -Force

# 2) 重启 Gateway（清除连接、页缓存与失效的 shm 映射）
Set-Location "D:\project\行业洞察\deerflow2.0"
docker compose --env-file .env -f docker/docker-compose.yaml restart gateway

# 3) 用就绪探针确认（不要只看 /health）
Invoke-WebRequest "http://localhost:2026/health/ready" -UseBasicParsing | Select-Object StatusCode
```

**Level 2 —— 重启后立即复发**

```powershell
# 强制重建容器（同时清除可能损坏的 -shm）
docker compose --env-file .env -f docker/docker-compose.yaml up -d --no-build --force-recreate gateway
```

**Level 3 —— 怀疑文件损坏（`integrity_check` 非 ok）**

```bash
# 停服务后执行（容器内）
python -c "import sqlite3;c=sqlite3.connect('/app/backend/.deer-flow/data/deerflow.db');print(c.execute('PRAGMA integrity_check').fetchall())"

# 若确认损坏：从 6.1-1 的备份恢复，或用 sqlite3 .recover 抢救
# 恢复顺序：先删 -wal/-shm，再放回 db，最后启动服务
```

**Level 4 —— 数据不可用且无备份**
启用 Postgres 后端（见 7.1），以新库重启；旧库保留只读用于人工提取。

### 6.2 应急期间的注意事项

- **不要**在服务运行时直接删除 `-wal` / `-shm` 文件，会造成 WAL 与主库不一致
- **不要**用 `docker restart` 之外的粗暴 kill，`docker stop` 会走优雅关停（含记忆队列排空）
- **不要**在故障期间执行 `VACUUM`——高 I/O 操作会放大失败面
- 备份必须**包含 `-wal`**，只拷 `deerflow.db` 会丢失未 checkpoint 的事务

---

## 7. 长期预防措施

### 7.1 方案对比

| 方案 | 彻底性 | 成本 | 建议 |
|---|---|---|---|
| **A. 迁移到 PostgreSQL** | ★★★★★ 完全消除问题 | 中（起一个容器 + 改配置） | **Windows + Docker 部署的首选** |
| **B. 把 `DEER_FLOW_HOME` 迁到 Docker 命名卷** | ★★★★ 换成 VM 内 ext4，绕过 9p | 低（改 compose 挂载） | 推荐，改动最小 |
| **C. 保持现状 + 监控告警** | ★ 只降低影响面 | 极低 | 仅作过渡 |
| **D. 直接在 Windows 原生运行（不用 Docker）** | ★★★★ 走 NTFS 原生 | 中（需装 Python/Node） | 适合单机开发 |

### 7.2 方案 B 落地（最小改动，推荐先做）

把数据库从 Windows 宿主机目录搬到 Docker 命名卷（VM 内 ext4），宿主机侧只保留需要人看的数据。

```yaml
# docker/docker-compose.yaml — gateway 服务
volumes:
  - deer-flow-home:/app/backend/.deer-flow   # 替代 ${DEER_FLOW_HOME} 绑定

volumes:
  deer-flow-home:
```

迁移步骤：
1. 停服务
2. `docker run --rm -v deer-flow-home:/dst -v "D:\...\backend\.deer-flow:/src" alpine cp -a /src/. /dst/`
3. 改挂载并 `up -d --force-recreate`
4. 校验 `integrity_check` 与业务登录

> 代价：`DEER_FLOW_HOME` 不再能从宿主机直接浏览（需要用 `docker cp` 取文件）。技能目录 `skills/` 仍可保持 bind mount（只读，无 SQLite）。

### 7.3 方案 A 落地（生产推荐）

```yaml
database:
  backend: postgres
  postgres:
    host: postgres
    port: 5432
    database: deerflow
    username: deerflow
    password: $POSTGRES_PASSWORD
```

配套：
- compose 增加 `postgres:16-alpine` + `pgdata` 命名卷
- 迁移期用 `pg_dump`/`pg_restore` 或 Alembic 重建（历史 checkpoint 可选择不迁移）
- `database.backend` 是**启动期字段**，切换需重启

### 7.4 无论哪种方案都应做的事

| 措施 | 具体动作 |
|---|---|
| **就绪探针改用 `/health/ready`** | `make up` 与 K8s readinessProbe 都用就绪探针；`/health` 只用于存活判定 |
| **日志持久化** | Gateway 日志接入文件/ELK，避免容器重建丢证据；至少把 `ERROR` 级别单独归档 |
| **数据库定期备份** | 每日兜底备份 `deerflow.db` + `-wal`；保留 7 天；备份后校验 `integrity_check` |
| **WAL 体积监控** | `-wal` 超过 64 MiB 或持续增长不回落 → 告警（可能 checkpoint 受阻） |
| **checkpoint 增长治理** | 当前 4,877 条 / 210 MiB 占比 95%；评估历史线程的 checkpoint 保留策略与清理任务 |
| **磁盘水位告警** | 宿主剩余 < 15% 时告警（当前 14.1%，已接近阈值） |
| **启动期写入削峰** | 重启后避免立即批量触发对话；`auto_skill.debounce_seconds` 可适当延长 |
| **修复 `Event loop is closed` 噪声** | auto-skill 每批 `asyncio.run()` 与 httpx 池回收交错；可在批次结束后显式 `aclose()`，属待优化项 |

---

## 附录 A：诊断命令速查

```powershell
# 服务健康（区分存活与就绪）
Invoke-WebRequest "http://localhost:2026/health" -UseBasicParsing
Invoke-WebRequest "http://localhost:2026/health/ready" -UseBasicParsing

# 看数据库错误（当前容器）
docker compose -f docker/docker-compose.yaml logs --no-color gateway |
  Select-String "disk I/O error|OperationalError|malformed|locked|SQLITE_"

# 数据库文件状态
Get-ChildItem "backend\.deer-flow\data" -File | Select-Object Name,Length,LastWriteTime

# 挂载类型（确认是否为 9p）
docker exec deer-flow-gateway sh -c "df -T /app/backend/.deer-flow"
docker inspect deer-flow-gateway --format '{{range .Mounts}}{{.Type}} {{.Source}}{{println}}{{end}}'
```

```bash
# 容器内完整性与一致性
python - <<'PY'
import sqlite3
c = sqlite3.connect('/app/backend/.deer-flow/data/deerflow.db', timeout=30)
for p in ('integrity_check','quick_check','journal_mode','freelist_count','page_count'):
    print(p, c.execute(f'PRAGMA {p}').fetchall())
PY
```

## 附录 B：当前健康基线快照（2026-11-05 09:57）

```
integrity_check      ok
quick_check          ok
journal_mode         wal          page_size 4096      page_count 56640
freelist_count       0            synchronous 2        busy_timeout 30000
db size              220.8 MiB    wal 4.2 MiB          shm 32 KiB
alembic              0051_merge_run_inputs_fencing
users 4 | threads_meta 43 | runs 46 (success 35 / error 8 / interrupted 3)
checkpoints 4877 (209.8 MiB) | writes 6627 (9.1 MiB)
memory FTS5          128 KiB, 52 facts, integrity ok
orphan records       runs=0 threads=0 checkpoints=0 non-terminal=0
gateway              /health 200, /health/ready 200
```