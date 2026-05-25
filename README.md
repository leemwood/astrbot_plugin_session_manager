# AstrBot Session Manager

让 LLM 能够自主管理 AstrBot 会话和定时任务的插件。

## 功能

### LLM Tools（由 AI 自动调用）

| 工具名 | 说明 | 权限 |
|--------|------|------|
| `list_sessions` | 列出所有对话会话（支持分页） | 无限制 |
| `view_messages` | 查看指定会话的对话消息 | 无限制 |
| `delete_session` | 删除指定会话及所有对话历史 | 需管理员 |
| `send_to_session` | 发送消息到指定会话 | 需管理员 |
| `list_cron_jobs` | 列出所有定时任务 | 无限制 |
| `delete_cron_job` | 删除指定定时任务 | 需管理员 |
| `toggle_cron_job` | 启用/禁用指定定时任务 | 需管理员 |

### 命令

| 命令 | 说明 | 权限 |
|------|------|------|
| `/sessions [page]` | 列出所有会话 | 无限制 |
| `/session <conversation_id> [page]` | 查看指定对话消息 | 无限制 |
| `/session_del <session_id>` | 删除指定会话 | ADMIN |
| `/cron_jobs` | 列出所有定时任务 | 无限制 |

## 配置

在 AstrBot WebUI 插件配置页面中设置：

- `admin_user_ids` — 管理员用户 ID 列表（可执行删除/发送等操作）
- `max_messages_per_page` — 每次查看消息返回的最大条数（默认 15）
- `list_page_size` — 列出会话时每页显示数（默认 20）
