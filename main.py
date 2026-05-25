from pathlib import Path

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, StarTools


class SessionManagerPlugin(Star):
    """会话管理插件 - 让 LLM 能够自主管理 AstrBot 会话。"""

    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.config: AstrBotConfig = config or {}
        self.data_dir: Path = StarTools.get_data_dir()

    # ──────────────────── 权限辅助 ────────────────────

    def _is_admin(self, event: AstrMessageEvent) -> bool:
        """检查发送者是否在管理员列表中。"""
        sender_id = str(event.get_sender_id())
        admin_ids = self.config.get("admin_user_ids", [])
        return sender_id in [str(a) for a in admin_ids]

    def _fmt_conversations(self, conversations: list, page: int = 1) -> str:
        """格式化会话列表为可读文本。"""
        lines = [f"📋 会话列表 (第 {page} 页, 共 {len(conversations)} 条):", ""]
        for conv in conversations:
            cid_short = conv.cid
            title = (conv.title or "(无标题)").strip()
            platform = conv.platform_id or "?"
            user = (conv.user_id or "?").split(":")[-1][:20]
            created = self._ts_fmt(conv.created_at)
            lines.append(
                f"  [{cid_short}] {title}"
            )
            lines.append(f"        平台={platform} 用户={user} token={conv.token_usage} 创建于{created}")
        return "\n".join(lines)

    def _fmt_messages(self, texts: list[str], page: int, total_pages: int) -> str:
        """格式化消息记录为可读文本。"""
        lines = [f"💬 对话消息 (第 {page}/{total_pages} 页):", ""]
        for text in texts:
            lines.append(f"  {text}")
        if total_pages > 1:
            lines.append("")
            lines.append(f"提示: 使用 view_messages 工具并指定 page={page + 1} 查看下一页")
        return "\n".join(lines)

    @staticmethod
    def _ts_fmt(ts: int) -> str:
        """将时间戳格式化为短日期字符串。"""
        import datetime
        if ts <= 0:
            return "?"
        dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
        return dt.strftime("%m-%d %H:%M")

    # ──────────────────── LLM Tools ────────────────────

    @filter.llm_tool(name="list_sessions")
    async def list_sessions(self, event: AstrMessageEvent, page: int = 1):
        """列出所有对话会话，支持分页。

        Args:
            page(int): 页码，从 1 开始。默认 1。
        """
        try:
            cm = self.context.conversation_manager
            page_size = int(self.config.get("list_page_size", 20))
            conversations, total = await cm.get_filtered_conversations(
                page=page, page_size=page_size
            )
            if not conversations:
                return "当前没有找到任何会话。"

            lines = [f"📋 会话列表 (第 {page} 页, 共 {total} 条):"]
            for conv in conversations:
                cid_short = conv.cid
                title = (conv.title or "(无标题)").strip()
                platform = conv.platform_id or "?"
                user = (conv.user_id or "?").split(":")[-1][:20]
                created = self._ts_fmt(conv.created_at)
                lines.append(f"\n  [{cid_short}] {title}")
                lines.append(f"        平台={platform} 用户={user} token={conv.token_usage} 创建于{created}")
            if total > page * page_size:
                lines.append(f"\n提示: 使用 list_sessions page={page + 1} 查看下一页")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"list_sessions failed: {e}")
            return f"获取会话列表失败: {e}"

    @filter.llm_tool(name="view_messages")
    async def view_messages(self, event: AstrMessageEvent, session_id: str, conversation_id: str, page: int = 1):
        """查看指定会话中某个对话的历史消息。

        Args:
            session_id(string): 会话标识 (unified_msg_origin)，如 "aiocqhttp:group:123456"
            conversation_id(string): 对话 ID (cid)，可以从 list_sessions 的结果中获取
            page(int): 页码，从 1 开始。默认 1。
        """
        try:
            cm = self.context.conversation_manager
            page_size = int(self.config.get("max_messages_per_page", 15))
            texts, total_pages = await cm.get_human_readable_context(
                unified_msg_origin=session_id,
                conversation_id=conversation_id,
                page=page,
                page_size=page_size,
            )
            if not texts:
                return "该对话没有消息记录，或者指定的会话/对话 ID 不存在。"

            lines = [f"💬 对话消息 (第 {page}/{total_pages} 页):"]
            for t in texts:
                lines.append(f"\n  {t}")
            if total_pages > 1 and page < total_pages:
                lines.append(f"\n提示: 使用 view_messages session_id=\"{session_id}\" conversation_id=\"{conversation_id}\" page={page + 1} 查看下一页")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"view_messages failed: {e}")
            return f"查看消息失败: {e}"

    @filter.llm_tool(name="delete_session")
    async def delete_session(self, event: AstrMessageEvent, session_id: str):
        """删除指定会话及其所有对话历史（需要管理员权限）。

        Args:
            session_id(string): 会话标识 (unified_msg_origin)，如 "aiocqhttp:group:123456"
        """
        if not self._is_admin(event):
            return "❌ 权限不足：只有管理员才能删除会话。请联系管理员配置 admin_user_ids。"

        try:
            cm = self.context.conversation_manager
            await cm.delete_conversations_by_user_id(unified_msg_origin=session_id)
            logger.warning(f"会话已删除: {session_id} (操作者: {event.get_sender_id()})")
            return f"✅ 已成功删除会话 {session_id} 及其所有对话历史。"
        except Exception as e:
            logger.error(f"delete_session failed: {e}")
            return f"删除会话失败: {e}"

    @filter.llm_tool(name="send_to_session")
    async def send_to_session(self, event: AstrMessageEvent, session_id: str, message: str):
        """向指定会话发送一条消息（需要管理员权限）。消息将以 Bot 身份发送到该会话。

        Args:
            session_id(string): 会话标识 (unified_msg_origin)，如 "aiocqhttp:group:123456"
            message(string): 要发送的消息内容
        """
        if not self._is_admin(event):
            return "❌ 权限不足：只有管理员才能发送消息。请联系管理员配置 admin_user_ids。"

        try:
            chain = MessageChain().message(message)
            success = await self.context.send_message(session_id, chain)
            if success:
                logger.info(f"消息已发送到会话 {session_id}: {message[:50]}... (操作者: {event.get_sender_id()})")
                return f"✅ 消息已成功发送到会话 {session_id}。"
            else:
                return "⚠️ 发送消息失败：send_message 返回失败。请检查会话 ID 是否正确。"
        except Exception as e:
            logger.error(f"send_to_session failed: {e}")
            return f"发送消息失败: {e}"

    # ──────────────────── Cron Job 辅助 ────────────────────

    @staticmethod
    def _fmt_cron_job(job) -> str:
        """格式化单个定时任务为可读文本。"""
        enabled_icon = "✅" if job.enabled else "⏸️"
        job_type_label = "主动" if job.job_type == "active_agent" else "基础"
        target = job.payload.get("unified_msg_origin") or job.payload.get("session_id", "?")
        next_run = ""
        if job.next_run_time:
            next_run = job.next_run_time.strftime("%m-%d %H:%M")
        lines = [
            f"{enabled_icon} [{job.job_id[:8]}] {job.name}",
            f"      类型={job_type_label} 目标会话={target}",
            f"      表达式={job.cron_expression or 'N/A'} 状态={job.status} 下次执行={next_run}",
        ]
        if job.description:
            lines.append(f"      描述={job.description[:60]}")
        return "\n".join(lines)

    # ──────────────────── Cron Job LLM Tools ────────────────────

    @filter.llm_tool(name="list_cron_jobs")
    async def list_cron_jobs(self, event: AstrMessageEvent):
        """列出所有已注册的定时任务（Cron Job），包括启用的和未启用的。"""
        try:
            cm = self.context.cron_manager
            jobs = await cm.list_jobs()
            if not jobs:
                return "当前没有设置任何定时任务。"

            active = [j for j in jobs if j.enabled]
            paused = [j for j in jobs if not j.enabled]
            lines = [f"📋 定时任务列表 (共 {len(jobs)} 个):", ""]
            if active:
                lines.append(f"▶️ 运行中 ({len(active)}):")
                for j in active:
                    lines.append("")
                    lines.append(self._fmt_cron_job(j))
            if paused:
                lines.append(f"\n⏸️ 已暂停 ({len(paused)}):")
                for j in paused:
                    lines.append("")
                    lines.append(self._fmt_cron_job(j))
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"list_cron_jobs failed: {e}")
            return f"获取定时任务列表失败: {e}"

    @filter.llm_tool(name="delete_cron_job")
    async def delete_cron_job(self, event: AstrMessageEvent, job_id: str):
        """删除指定的定时任务（需要管理员权限）。

        Args:
            job_id(string): 定时任务 ID（完整 job_id 或前8位）
        """
        if not self._is_admin(event):
            return "❌ 权限不足：只有管理员才能删除定时任务。"

        try:
            cm = self.context.cron_manager
            jobs = await cm.list_jobs()
            match = self._match_job(jobs, job_id)
            if not match:
                return f"❌ 未找到定时任务: {job_id}"

            await cm.delete_job(match.job_id)
            logger.warning(f"定时任务已删除: {match.name}({match.job_id}) (操作者: {event.get_sender_id()})")
            return f"✅ 已删除定时任务「{match.name}」({match.job_id[:8]}...)"
        except Exception as e:
            logger.error(f"delete_cron_job failed: {e}")
            return f"删除定时任务失败: {e}"

    @filter.llm_tool(name="toggle_cron_job")
    async def toggle_cron_job(self, event: AstrMessageEvent, job_id: str, enabled: bool):
        """启用或禁用指定的定时任务（需要管理员权限）。

        Args:
            job_id(string): 定时任务 ID（完整 job_id 或前8位）
            enabled(bool): true=启用, false=禁用
        """
        if not self._is_admin(event):
            return "❌ 权限不足：只有管理员才能修改定时任务。"

        try:
            cm = self.context.cron_manager
            jobs = await cm.list_jobs()
            match = self._match_job(jobs, job_id)
            if not match:
                return f"❌ 未找到定时任务: {job_id}"

            await cm.update_job(match.job_id, enabled=enabled)
            action = "启用" if enabled else "禁用"
            logger.warning(f"定时任务已{action}: {match.name}({match.job_id}) (操作者: {event.get_sender_id()})")
            icon = "✅" if enabled else "⏸️"
            return f"{icon} 已{action}定时任务「{match.name}」({match.job_id[:8]}...)"
        except Exception as e:
            logger.error(f"toggle_cron_job failed: {e}")
            return f"修改定时任务失败: {e}"

    @staticmethod
    def _match_job(jobs: list, job_id: str) -> object | None:
        """按完整ID或前8位匹配定时任务。"""
        job_id = job_id.strip()
        for j in jobs:
            if j.job_id == job_id or j.job_id.startswith(job_id):
                return j
        return None

    # ──────────────────── 命令 ────────────────────

    @filter.command("sessions")
    async def cmd_sessions(self, event: AstrMessageEvent, page: int = 1):
        """列出当前所有对话会话。"""
        try:
            cm = self.context.conversation_manager
            page_size = int(self.config.get("list_page_size", 20))
            conversations, total = await cm.get_filtered_conversations(
                page=page, page_size=page_size
            )
            if not conversations:
                yield event.plain_result("当前没有找到任何会话。")
                return

            lines = [f"📋 会话列表 (第 {page} 页, 共 {total} 条):\n"]
            for conv in conversations:
                cid_short = conv.cid
                title = (conv.title or "(无标题)").strip()
                platform = conv.platform_id or "?"
                user = (conv.user_id or "?").split(":")[-1][:20]
                lines.append(f"  [{cid_short}] {title}")
                lines.append(f"        平台={platform} 用户={user}")
            if total > page * page_size:
                lines.append(f"\n使用 /sessions page={page + 1} 查看下一页")
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"/sessions failed: {e}")
            yield event.plain_result(f"获取会话列表失败: {e}")

    @filter.command("session")
    async def cmd_session(self, event: AstrMessageEvent, conversation_id: str, page: int = 1):
        """查看指定对话的消息记录。

        Args:
            conversation_id: 对话 ID (cid)，可以从 /sessions 获取
            page: 页码，默认 1
        """
        try:
            cm = self.context.conversation_manager
            umo = event.unified_msg_origin

            texts, total_pages = await cm.get_human_readable_context(
                unified_msg_origin=umo,
                conversation_id=conversation_id,
                page=page,
                page_size=int(self.config.get("max_messages_per_page", 15)),
            )
            if not texts:
                yield event.plain_result("该对话没有消息记录。")
                return

            lines = [f"💬 对话消息 (第 {page}/{total_pages} 页):"]
            for t in texts:
                lines.append(f"\n  {t}")
            if total_pages > 1 and page < total_pages:
                lines.append(f"\n使用 /session {conversation_id} page={page + 1} 查看下一页")
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"/session failed: {e}")
            yield event.plain_result(f"查看对话失败: {e}")

    @filter.command("session_del")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def cmd_session_del(self, event: AstrMessageEvent, session_id: str):
        """[管理员] 删除指定会话的所有对话历史。

        Args:
            session_id: 会话标识 (unified_msg_origin)
        """
        try:
            cm = self.context.conversation_manager
            await cm.delete_conversations_by_user_id(unified_msg_origin=session_id)
            logger.warning(f"会话已删除: {session_id} (操作者: {event.get_sender_id()})")
            yield event.plain_result(f"✅ 已删除会话: {session_id}")
        except Exception as e:
            logger.error(f"/session_del failed: {e}")
            yield event.plain_result(f"删除会话失败: {e}")

    @filter.command("cron_jobs")
    async def cmd_cron_jobs(self, event: AstrMessageEvent):
        """列出所有已注册的定时任务。"""
        try:
            cm = self.context.cron_manager
            jobs = await cm.list_jobs()
            if not jobs:
                yield event.plain_result("当前没有设置任何定时任务。")
                return

            active = [j for j in jobs if j.enabled]
            paused = [j for j in jobs if not j.enabled]
            lines = [f"📋 定时任务列表 (共 {len(jobs)} 个):", ""]
            if active:
                lines.append(f"▶️ 运行中 ({len(active)}):")
                for j in active:
                    lines.append("")
                    lines.append(self._fmt_cron_job(j))
            if paused:
                lines.append(f"\n⏸️ 已暂停 ({len(paused)}):")
                for j in paused:
                    lines.append("")
                    lines.append(self._fmt_cron_job(j))
            yield event.plain_result("\n".join(lines))
        except Exception as e:
            logger.error(f"/cron_jobs failed: {e}")
            yield event.plain_result(f"获取定时任务列表失败: {e}")

    async def terminate(self):
        """插件卸载时调用。"""
        logger.info("SessionManagerPlugin 已卸载。")
