# CeCeMate 产品手册问答

产品手册作为只读知识提供方随 Gateway 部署，所有已登录用户共享同一版语料。聊天中询问平台功能、菜单入口和指标口径时，助手通过 `knowledge_search` 获取手册证据；真实业务数据继续使用现有取数工具。知识库选择器关闭。

## 内容依据

语料以操作方提供的 V1.1 产品手册为依据，不校正其业务事实，保留章节差异与冲突。仅按原文明示的章节下线状态处理，不按“舆情”“公告”等词全局排除。清除图片地址、作者和内部编辑标注，保留表格、数字、功能点、来源行号。

每条证据包含章节和手册版本。额度和更新频率属于手册记载，不是当前账号状态；平台具备的功能不代表助手当前具有对应执行工具。没有明确 URL 时仅说明菜单路径。无命中与检索故障分别表述。

## 发布与更新

扩展源位于 `examples/deerflow-extension-cecemate-manual/`。原始手册留在操作方文件目录，不提交。生成语料、运行包测试并检查 wheel 后，通过扩展管理器安装或升级；管理器生成 `backend/extensions/sources/` 快照并修改依赖及锁文件。生产镜像直接从受控快照安装，不在容器启动时解析依赖。

```powershell
uv run --no-sync --project backend deerflow extensions install examples/deerflow-extension-cecemate-manual --yes --required
# 已安装时使用 upgrade 子命令，参数相同但不传 --required。
```

实际环境 `config.yaml` 需合并扩展注册、`knowledge_base`、`knowledge_search` 工具及产品问答提示词。仓库的部署示例不会自动覆盖服务器的配置文件。

每次更新重新构建语料、检查检索用例、升级快照并重建 Gateway 镜像，重启 Gateway 后生效。已开始的会话运行保持其原有运行快照。回滚时恢复上一版扩展快照、依赖锁及对应配置，重建并重启。

## 限制

首期不提供在线上传、编辑、截图 OCR、自动更新手册或账号差异化知识权限。模型自动查询由工具可见性和提示词驱动，离线检索通过不等于线上模型调用策略已通过验收；线上问答验收需使用实际模型。

## 首版语料审计

本次输入共 3964 行，生成 164 条章节记录，其中 159 条有效、5 条明确下线。移除 216 个图片引用和 34 处编辑作者标注。构建清单记录输入及输出校验和、章节来源范围和逐行归属，未归属行数为零。

正文中的数字、表格、定义、限制及冲突表述均保留。仅从明确标签提取结构化字段；原文没有明确入口或定义标签时字段留空，不代表正文中没有相关说明。相同功能在不同章节的表述保留各自来源，检索时去除重复证据，不在构建阶段做可能改变业务含义的语义合并。

可重复构建命令（原始手册由操作方提供，不放在仓库中）：

```powershell
uv run --no-sync --project backend python examples/deerflow-extension-cecemate-manual/scripts/build_corpus.py "原始手册.md" examples/deerflow-extension-cecemate-manual/deerflow_extension_cecemate_manual/data
uv run --no-sync --project backend pytest examples/deerflow-extension-cecemate-manual/tests -q
uv run --no-sync --project backend python scripts/check_extension.py examples/deerflow-extension-cecemate-manual
```
