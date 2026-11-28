# Conversation UI ownership

This expands the ownership index in `frontend/src/AGENTS.md`.

- `src/components/workspace/model-picker-content.tsx` owns the compact model
  list, favorite grouping, and the anchored non-modal picker shared by the main
  composer and Side Chat. Each row keeps model selection and its inline
  favorite star as sibling buttons. The picker deliberately follows the
  pre-favorites two-line row density and does not add a search field. Favorites
  are stored by
  `core/models/favorites-store.ts` under a user-scoped browser key and only
  reorder derived display arrays: never sort `useModels().models`, promote a
  favorite to the default model, prune a temporarily unavailable favorite, or
  merge the main and Side Chat selection callbacks. Keep favorite buttons out
  of model-selection buttons; the two call sites continue to own their triggers
  and their distinct mode/reasoning-effort transitions.
- `src/app/workspace/chats/[thread_id]/page.tsx` owns composer busy-state wiring.
- `src/app/workspace/chats/[thread_id]/page.tsx` owns branch-from-turn submission and navigation; sidecar `MessageList` instances do not receive the branch action.
- `core/threads/thread-branch-tree.ts` projects only loaded, same-pin branch lineage into Recent chats. Missing, malformed, cross-pin, self, or cyclic parents stay top-level; unpinned groups follow their freshest descendant while pinned root order stays stable. `recent-chat-list.tsx` caps visual indentation without changing the recursive order.
- `src/app/workspace/chats/[thread_id]/page.tsx` and `src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx` own edit-and-rerun submission wiring because the page must preserve normal/custom-agent run context; `MessageList` only detects the latest editable user turn and renders the inline editor.
- `src/app/workspace/chats/[thread_id]/page.tsx` gates the Workspace Browser trigger and browser right panel on `/api/features -> browser_control.enabled`; `src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx` applies the same capability gate and additionally requires the Custom Agent's tool groups to be unrestricted or include `browser`. Default/failed feature discovery hides the browser control so optional backend installs do not show a dead Live socket.
- `src/app/workspace/chats/[thread_id]/page.tsx` and `src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx` own active-goal display state for their composer overlays.
- `src/components/workspace/messages/message-list.tsx` owns human-input card answered/latest/pending gating; entry pages only translate a submitted card response into `sendMessage` calls.
- `src/components/workspace/browser-view/browser-view-panel.tsx` forwards each physical pointer click as one `click` input; do not also emit `down`/`up` for the same gesture because the remote Playwright click would run twice.
- `src/components/workspace/browser-view/use-browser-stream.ts` requests binary JPEG
  frames with `frame_format=binary`; status, URL, tabs, and navigation rejection
  messages remain JSON. `LatestBrowserFrameBuffer` keeps only the newest pending
  frame, publishes through `useSyncExternalStore` at most once per animation
  frame, and owns object-URL revocation. Keep the Gateway's legacy JSON/base64
  frame path for older clients.

## CeCeMate 首页素材

新任务首页使用 `public/images/cecemate-home/` 下的素材。下载设计稿素材后按下表覆盖同名文件，尺寸为页面上的 CSS 像素。PNG 可以按两倍或三倍尺寸导出，保持宽高比即可。

| 位置                                                   | 文件名                                                                                                                                        | 显示尺寸         |
| ------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------- | ---------------- |
| 首页人物                                               | `cecemate-avatar.png`                                                                                                                         | 120 × 146        |
| “Hi, 我是”标题                                         | `greeting-hi-im.svg`                                                                                                                          | 129 × 32         |
| “CeCeMate”标题                                         | `greeting-cecemate.svg`                                                                                                                       | 190 × 32         |
| 产业分析一页纸                                         | `card-industry.png`                                                                                                                           | 260 × 140        |
| 商机清单                                               | `card-opportunities.png`                                                                                                                      | 260 × 140        |
| 企业风险扫描                                           | `card-risk.png`                                                                                                                               | 260 × 140        |
| 开启新任务图标、文字                                   | `new-task-icon.svg`、`new-task-label.svg`                                                                                                     | 20 × 20、80 × 22 |
| 技能、MCP 服务                                         | `nav-skills.svg`、`nav-mcp.svg`                                                                                                               | 各 16 × 16       |
| 运行中、中断、错误、未读                               | `task-busy.svg`、`task-interrupted.svg`、`task-error.svg`、`task-unread.svg`                                                                  | 各 10 × 10       |
| 折叠、展开侧栏                                         | `sidebar-collapse.svg`、`sidebar-expand.svg`                                                                                                  | 各 16 × 16       |
| 搜索、下拉箭头                                         | `search.svg`、`chevron-down.svg`                                                                                                              | 14–16、12–14     |
| 输入框添加、上传、引用产物、技能                       | `composer-add.svg`、`composer-upload.svg`、`composer-artifact.svg`、`composer-skill.svg`                                                      | 18、16、16、16   |
| 润色、撤销润色                                         | `composer-polish.svg`、`composer-polish-undo.svg`                                                                                             | 各 16 × 16       |
| 选中、胶囊移除                                         | `composer-check.svg`、`chip-remove.svg`                                                                                                       | 14、12           |
| 快速响应、思考模式、深度研究                           | `mode-fast.svg`、`mode-thinking.svg`、`mode-research.svg`                                                                                     | 各 16 × 16       |
| DeepSeek、Qwen、GLM、通用模型                          | `model-deepseek.svg`、`model-qwen.svg`、`model-glm.svg`、`model-generic.svg`                                                                  | 各 16 × 16       |
| Word、PDF、Excel、图片、代码、通用文件                 | `file-word.svg`、`file-pdf.svg`、`file-excel.svg`、`file-image.svg`、`file-code.svg`、`file-generic.svg`                                      | 各 16–18 × 16–18 |
| 企业风险、深度研究、数据分析、数据可视化、报告撰写技能 | `skill-enterprise-risk.svg`、`skill-deep-research.svg`、`skill-data-analysis.svg`、`skill-data-visualization.svg`、`skill-report-writing.svg` | 各 18 × 18       |

任务列表使用会话的 `status` 字段。运行中、中断和错误优先展示对应图标。空闲且未读时显示蓝点，空闲且已读时留空。搜索按任务标题匹配，Esc 退出搜索。
