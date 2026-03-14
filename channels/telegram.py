# -*- coding: utf-8 -*-
"""
ArcMind Channels — Telegram Channel
======================================
Telegram Bot 通道：接收 Telegram 消息 → 轉為 InboundMessage → 送入 Gateway。
移植自 ARCHILLX v0.44 channels/telegram.py + integrations/telegram_polling.py。

使用 python-telegram-bot polling 模式（無需 webhook）。
所有消息通過 Gateway pipeline 統一處理。

支援指令：
  /start — 歡迎消息
  /help — 指令列表
  /model — 切換 AI 模型（InlineKeyboard）
  /mode — 切換輸出模式（簡潔/詳細/程式碼）
  /status, /cancel, /reset, /skills, /models, /health, /version
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

try:
    from telegram.constants import ChatAction
except ImportError:
    ChatAction = None  # type: ignore

from channels.base import Channel
from gateway.router import InboundMessage, OutboundMessage
from gateway.server import process_message, delivery_queue

logger = logging.getLogger("arcmind.channels.telegram")


# ── Per-session preferences (in-memory) ──────────────────────────────────────

_session_prefs: dict[str, dict] = {}


def get_session_pref(session_id: str) -> dict:
    """Get preferences for a session."""
    if session_id not in _session_prefs:
        _session_prefs[session_id] = {
            "model_override": "",      # e.g. "openai:gpt-4o"
            "output_mode": "default",  # default | concise | detailed | code
        }
    return _session_prefs[session_id]


# ── Model Catalog ────────────────────────────────────────────────────────────

_MODEL_CATALOG = [
    ("🔵 Claude 3.7",       "anthropic:claude-3-7-sonnet-20250219"),
    ("🟢 GPT-4o",            "openai:gpt-4o"),
    ("🧠 o3-mini",           "openai:o3-mini"),
    ("💎 Gemini 2.0",        "google:gemini-2.0-flash"),
    ("🐋 DeepSeek V3",       "deepseek:deepseek-chat"),
    ("🧠 DeepSeek R1",       "deepseek:deepseek-reasoner"),
    ("✖️ xAI Grok-3",        "xai:grok-3"),
    ("🟠 Groq 70B",          "groq:llama-3.3-70b-versatile"),
    ("🟡 MiniMax M2.5",      "minimax:MiniMax-M2.5"),
    ("🌙 Kimi (Moonshot)",   "moonshot:moonshot-v1-auto"),
    ("🟣 Zhipu GLM-4",       "zhipu:glm-4-plus"),
    ("🌐 OpenRouter",        "openrouter:auto"),
    ("🏠 Ollama 本地",       "ollama:auto"),
    ("☁️ Ollama 遠端",       "ollama_remote:auto"),
    ("↩️ 自動選擇",          ""),
]

_MODE_CATALOG = [
    ("⚡ 簡潔模式", "concise",  "短回答，重點式"),
    ("📝 詳細模式", "detailed", "完整解釋，步驟清楚"),
    ("💻 程式碼模式", "code",   "優先輸出程式碼"),
    ("🔄 默認模式", "default",  "智能判斷"),
]


# ── Tool Categories for /tools browsing ────────────────────────────────────

_TOOL_CATEGORIES = {
    "📂 檔案與系統": [
        "file_ops", "read_file", "write_file", "process_skill",
        "archive_skill", "clipboard_skill", "screenshot_skill",
    ],
    "🔍 搜尋與網路": [
        "web_search", "browser_skill", "network_skill",
        "read_url_content", "api_tester",
    ],
    "💻 開發工具": [
        "code_exec", "code_assistant", "run_command",
        "git_skill", "github_skill", "gitnexus_skill",
        "docker_skill", "ssh_skill",
    ],
    "📝 文件與資料": [
        "document_skill", "pdf_skill", "json_tool", "text_tool",
        "regex_skill", "hash_skill", "ocr_skill", "marp_skill",
        "summarize_skill", "presenton_skill",
    ],
    "🤖 Agent 管理": [
        "agent_delegation", "agent_builder", "worker_heartbeat",
        "invoke_skill", "self_iteration",
    ],
    "📡 通訊整合": [
        "slack_skill", "email_skill", "discord_skill",
        "notion_skill", "obsidian_skill", "google_workspace",
        "notification_skill",
    ],
    "🛠️ 工具與轉換": [
        "translation_skill", "qrcode_skill", "image_gen",
        "pexels_skill", "weather_skill", "database_skill",
        "memory_kg",
    ],
    "📊 排程與監控": [
        "cron_skill", "ai_trend_monitor", "daily_report",
        "security_scan", "arctest", "env_discovery",
        "federation_sync", "approval_gate_sweep",
    ],
}


class TelegramChannel(Channel):
    """
    Telegram Bot channel using long-polling.

    Config via environment:
      TELEGRAM_BOT_TOKEN  — Bot token from @BotFather
      TELEGRAM_CHAT_ID    — Authorized chat ID (optional, for security)
    """

    def __init__(self, token: str = "", chat_id: str = ""):
        token = token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        enabled = bool(token.strip())
        super().__init__(name="Telegram", enabled=enabled)

        self.token = token
        self.allowed_chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self._app = None  # telegram.ext.Application
        try:
            from version import __version__
            self._version = __version__
        except Exception:
            self._version = "0.7.0"

    async def start(self) -> None:
        """Start Telegram long-polling."""
        if not self.enabled:
            logger.warning("[Telegram] No TELEGRAM_BOT_TOKEN set, skipping")
            return

        try:
            from telegram import Update
            from telegram.ext import (
                Application, CommandHandler, MessageHandler,
                CallbackQueryHandler, filters,
            )
        except ImportError:
            logger.error(
                "[Telegram] python-telegram-bot not installed. "
                "Run: pip install python-telegram-bot"
            )
            return

        self._running = True
        logger.info("[Telegram] Starting bot polling...")

        # 同步 OODA 路徑直接返回結果，不再需要 DeliveryQueue 推送

        app = Application.builder().token(self.token).concurrent_updates(True).build()

        # Register handlers
        app.add_handler(CommandHandler("start", self._handle_start))
        app.add_handler(CommandHandler("model", self._handle_model_cmd))
        app.add_handler(CommandHandler("mode", self._handle_mode_cmd))
        app.add_handler(CommandHandler("tools", self._handle_tools_cmd))
        app.add_handler(CallbackQueryHandler(
            self._handle_callback, pattern=r"^model:"))
        app.add_handler(CallbackQueryHandler(
            self._handle_callback, pattern=r"^mode:"))
        app.add_handler(CallbackQueryHandler(
            self._handle_tools_callback, pattern=r"^tools:"))
        # V3: Approval gate inline keyboard callbacks
        app.add_handler(CallbackQueryHandler(
            self._handle_approval_callback, pattern=r"^approve:|^reject:"))
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            self._handle_message,
        ))
        # Voice messages
        app.add_handler(MessageHandler(
            filters.VOICE | filters.AUDIO,
            self._handle_voice,
        ))
        # Location messages
        app.add_handler(MessageHandler(
            filters.LOCATION,
            self._handle_location,
        ))
        # Photo messages
        app.add_handler(MessageHandler(
            filters.PHOTO,
            self._handle_photo,
        ))

        # Handle all other commands through gateway
        app.add_handler(MessageHandler(
            filters.COMMAND,
            self._handle_command,
        ))

        self._app = app

        # Start polling (blocking until stopped)
        try:
            await app.initialize()
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)

            # Wait until stopped
            while self._running:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            pass
        finally:
            try:
                if app.updater and app.updater.running:
                    await app.updater.stop()
                if app.running:
                    await app.stop()
                await app.shutdown()
            except Exception as cleanup_err:
                logger.warning("[Telegram] Cleanup error (safe to ignore): %s", cleanup_err)
            self._running = False

    async def stop(self) -> None:
        """Stop Telegram polling."""
        self._running = False
        logger.info("[Telegram] Stopping bot...")

    async def send(self, message: OutboundMessage) -> bool:
        """Send a message back to Telegram, including any attachments."""
        if not self._app or not self._app.bot:
            return False

        chat_id = message.metadata.get("chat_id", self.allowed_chat_id)
        if not chat_id:
            logger.warning("[Telegram] No chat_id for outbound message")
            return False

        success = True

        # 1. Send text if present
        if message.text and message.text.strip():
            try:
                await self._app.bot.send_message(
                    chat_id=int(chat_id),
                    text=message.text,
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error("[Telegram] Send text failed: %s", e)
                # Retry without markdown
                try:
                    await self._app.bot.send_message(
                        chat_id=int(chat_id),
                        text=message.text,
                    )
                except Exception as e2:
                    logger.error("[Telegram] Send retry failed: %s", e2)
                    success = False

        # 2. Send attachments if any
        if hasattr(message, "attachments") and message.attachments:
            from pathlib import Path
            for att in message.attachments:
                file_path = att.get("path")
                if not file_path or not Path(file_path).exists():
                    logger.warning("[Telegram] Attachment file not found: %s", file_path)
                    continue
                    
                try:
                    logger.info("[Telegram] Sending attachment: %s", file_path)
                    filename = Path(file_path).name
                    with open(file_path, "rb") as f:
                        if file_path.endswith(('.png', '.jpg', '.jpeg', '.gif')):
                            await self._app.bot.send_photo(
                                chat_id=int(chat_id), 
                                photo=f,
                                filename=filename
                            )
                        elif file_path.endswith(('.mp3', '.ogg', '.wav')):
                            await self._app.bot.send_voice(
                                chat_id=int(chat_id), 
                                voice=f,
                                filename=filename
                            )
                        else:
                            await self._app.bot.send_document(
                                chat_id=int(chat_id), 
                                document=f,
                                filename=filename
                            )
                except Exception as e:
                    logger.error("[Telegram] Send attachment failed: %s", e)
                    success = False

        return success

    # ── Telegram Handlers ───────────────────────────────────────────────

    async def _handle_start(self, update, context) -> None:
        """Handle /start command."""
        pref = get_session_pref(f"tg_{update.effective_chat.id}")
        model = pref["model_override"] or "自動"
        mode = pref["output_mode"]
        await update.message.reply_text(
            f"🧠 *ArcMind v{self._version}*\n"
            "Hi! I'm ArcMind, your autonomous AI assistant.\n\n"
            f"📡 當前模型：`{model}`\n"
            f"📋 輸出模式：`{mode}`\n\n"
            "⚡ 快速切換：\n"
            "• /model — 切換 AI 模型\n"
            "• /mode — 切換輸出模式\n"
            "• /help — 查看所有指令",
            parse_mode="Markdown",
        )

    async def _handle_model_cmd(self, update, context) -> None:
        """Handle /model — show model selection InlineKeyboard."""
        if not self._check_auth(update):
            return

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        session_id = f"tg_{update.effective_chat.id}"
        pref = get_session_pref(session_id)
        current = pref["model_override"] or "auto"

        # Check which providers are actually available
        try:
            from runtime.model_router import model_router
            available = {p["provider"] for p in model_router.list_providers()}
        except Exception:
            available = set()

        # Build keyboard with 2 buttons per row
        buttons = []
        row = []
        for label, model_str in _MODEL_CATALOG:
            if model_str:
                provider = model_str.split(":")[0]
                if provider not in available:
                    continue  # Skip unavailable providers
            is_active = (model_str == pref["model_override"])
            display = f"{'✅ ' if is_active else ''}{label}"
            row.append(InlineKeyboardButton(display, callback_data=f"model:{model_str}"))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        reply_markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(
            "🤖 *選擇 AI 模型*\n"
            f"當前：`{current}`\n\n"
            "點選下方按鈕切換：",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

    async def _handle_mode_cmd(self, update, context) -> None:
        """Handle /mode — show output mode selection."""
        if not self._check_auth(update):
            return

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        session_id = f"tg_{update.effective_chat.id}"
        pref = get_session_pref(session_id)

        buttons = []
        for label, mode_key, desc in _MODE_CATALOG:
            is_active = (mode_key == pref["output_mode"])
            display = f"{'✅ ' if is_active else ''}{label}"
            buttons.append([InlineKeyboardButton(
                f"{display} — {desc}", callback_data=f"mode:{mode_key}"
            )])

        reply_markup = InlineKeyboardMarkup(buttons)
        await update.message.reply_text(
            "📋 *選擇輸出模式*\n"
            f"當前：`{pref['output_mode']}`\n\n"
            "點選下方按鈕切換：",
            reply_markup=reply_markup,
            parse_mode="Markdown",
        )

    async def _handle_callback(self, update, context) -> None:
        """Handle InlineKeyboard button presses for model/mode switching."""
        query = update.callback_query
        await query.answer()

        chat_id = query.message.chat_id
        session_id = f"tg_{chat_id}"
        pref = get_session_pref(session_id)
        data = query.data  # e.g. "model:openai:gpt-4o" or "mode:concise"

        if data.startswith("model:"):
            model_str = data[6:]  # Remove "model:" prefix
            pref["model_override"] = model_str
            if model_str:
                display = model_str
                for label, m in _MODEL_CATALOG:
                    if m == model_str:
                        display = f"{label} (`{model_str}`)"
                        break
                await query.edit_message_text(
                    f"✅ 模型已切換為 {display}\n\n"
                    "後續對話將使用此模型。\n"
                    "使用 /model 可隨時更換。",
                    parse_mode="Markdown",
                )
            else:
                await query.edit_message_text(
                    "✅ 已切換為*自動選擇*模式\n\n"
                    "ArcMind 會根據任務類型自動選擇最佳模型。",
                    parse_mode="Markdown",
                )

            logger.info("[Telegram] Model switched: session=%s model=%s",
                        session_id, model_str or "auto")

        elif data.startswith("mode:"):
            mode = data[5:]
            pref["output_mode"] = mode
            mode_desc = mode
            for label, key, desc in _MODE_CATALOG:
                if key == mode:
                    mode_desc = f"{label} — {desc}"
                    break
            await query.edit_message_text(
                f"✅ 輸出模式已切換為 {mode_desc}\n\n"
                "使用 /mode 可隨時更換。",
                parse_mode="Markdown",
            )

            logger.info("[Telegram] Mode switched: session=%s mode=%s",
                        session_id, mode)

    async def _handle_approval_callback(self, update, context) -> None:
        """V3: Handle approval gate ✅/❌ button presses from Telegram."""
        query = update.callback_query
        await query.answer()

        data = query.data  # e.g. "approve:42" or "reject:42"
        chat_id = query.message.chat_id
        session_id = f"tg_{chat_id}"

        try:
            if data.startswith("approve:"):
                gate_id = int(data[8:])
                decision = "approved"
            elif data.startswith("reject:"):
                gate_id = int(data[7:])
                decision = "rejected"
            else:
                return

            # Decide the gate
            from runtime.approval_gate import approval_gate
            result = approval_gate.decide(
                gate_id=gate_id,
                decision=decision,
                decided_by=f"telegram:{chat_id}",
            )

            if "error" in result:
                await query.edit_message_text(f"❌ 審批失敗: {result['error']}")
                return

            emoji = "✅" if decision == "approved" else "❌"
            await query.edit_message_text(
                f"{emoji} 審批閘門 #{gate_id} 已{decision}\n"
                f"操作: {result.get('trigger_reason', '')[:100]}",
            )

            # Emit APPROVAL_DECIDED event → resume/cancel task
            try:
                from runtime.event_bus import event_bus, Event, EventType
                event_bus.emit(Event(
                    type=EventType.APPROVAL_DECIDED,
                    source="telegram_callback",
                    payload={
                        "gate_id": gate_id,
                        "decision": decision,
                        "task_id": result.get("task_id", ""),
                        "session_id": result.get("session_id", session_id),
                    },
                ))
            except Exception:
                pass

            logger.info("[Telegram] Approval gate %d %s by chat %s", gate_id, decision, chat_id)

        except (ValueError, IndexError) as e:
            await query.edit_message_text(f"❌ 無效的審批操作: {e}")
        except Exception as e:
            logger.error("[Telegram] Approval callback error: %s", e)
            await query.edit_message_text(f"❌ 審批處理失敗: {e}")

    async def _handle_message(self, update, context) -> None:
        """Handle regular text messages."""
        if not self._check_auth(update):
            return

        chat_id = update.effective_chat.id
        session_id = f"tg_{chat_id}"

        # Inject per-session preferences into metadata
        pref = get_session_pref(session_id)

        # Convert to InboundMessage
        msg = InboundMessage.from_telegram(
            update.to_dict(),
            chat_id=chat_id,
        )

        # Inject model/mode overrides into metadata
        if pref["model_override"]:
            msg.metadata["model_override"] = pref["model_override"]
        if pref["output_mode"] != "default":
            msg.metadata["output_mode"] = pref["output_mode"]

        # Process through Gateway
        try:
            # Show typing indicator
            logger.info("[Telegram] Sending typing indicator to chat=%s", chat_id)
            if ChatAction:
                await context.bot.send_chat_action(
                    chat_id=chat_id, action=ChatAction.TYPING)

            # Start periodic typing refresh (Telegram typing expires after ~5s)
            typing_task = asyncio.create_task(
                self._keep_typing(context.bot, chat_id))

            try:
                response = await process_message(msg)
                
                # If there's an immediate synchronous response (like /status), send it now.
                # Async agent tasks usually return an empty text because they respond later via queue.
                if response and response.text:
                    out = OutboundMessage(
                        session_id=msg.session_id,
                        text=response.text,
                        channel="telegram",
                        metadata={"chat_id": str(chat_id)},
                    )
                    await self.send(out)
            finally:
                typing_task.cancel()

        except Exception as e:
            logger.exception("[Telegram] Message processing error: %s", e)
            await update.message.reply_text(f"⚠️ 處理失敗: {e}")

    async def _handle_voice(self, update, context) -> None:
        """Handle voice messages: STT → process → TTS → reply."""
        if not self._check_auth(update):
            return

        chat_id = update.effective_chat.id
        session_id = f"tg_{chat_id}"

        try:
            # Show typing
            if ChatAction:
                await context.bot.send_chat_action(
                    chat_id=chat_id, action=ChatAction.TYPING)

            # Download voice file
            voice = update.message.voice or update.message.audio
            if not voice:
                await update.message.reply_text("⚠️ 無法讀取語音訊息")
                return

            file = await context.bot.get_file(voice.file_id)
            import tempfile
            from pathlib import Path
            ogg_path = Path(tempfile.gettempdir()) / f"arcmind_voice/{voice.file_id}.ogg"
            ogg_path.parent.mkdir(exist_ok=True)
            await file.download_to_drive(str(ogg_path))

            logger.info("[Telegram] Voice received: %s (%d bytes)",
                        voice.file_id, voice.file_size or 0)

            # STT: Voice → Text
            from channels.voice import voice_to_text
            user_text = await voice_to_text(ogg_path)

            if not user_text:
                await update.message.reply_text("🎤 無法辨識語音內容，請重試。")
                return

            # Show transcription
            await update.message.reply_text(f"🎤 辨識內容：{user_text}")

            # Process through Gateway (same as text)
            pref = get_session_pref(session_id)
            msg = InboundMessage(
                channel="telegram",
                user_id=str(update.effective_user.id),
                session_id=session_id,
                text=user_text,
                metadata={
                    "chat_id": str(chat_id),
                    "source": "voice",
                    "model_override": pref["model_override"] or "",
                    "output_mode": pref["output_mode"],
                },
            )

            # Keep typing while processing
            typing_task = asyncio.create_task(
                self._keep_typing(context.bot, chat_id))

            try:
                response = await process_message(msg)
            finally:
                typing_task.cancel()

            response_text = response.text

            # TTS: Text → Voice
            try:
                from channels.voice import text_to_voice
                voice_ogg = await text_to_voice(response_text)

                # Send voice reply
                with open(voice_ogg, "rb") as vf:
                    await context.bot.send_voice(
                        chat_id=chat_id,
                        voice=vf,
                        caption=response_text[:1024] if len(response_text) < 1024 else None,
                    )

                # If text is long, also send as text
                if len(response_text) >= 1024:
                    out = OutboundMessage(
                        session_id=session_id,
                        text=response_text,
                        channel="telegram",
                        metadata={"chat_id": str(chat_id)},
                    )
                    await self.send(out)

            except Exception as tts_err:
                logger.warning("[Telegram] TTS failed, sending text only: %s", tts_err)
                out = OutboundMessage(
                    session_id=session_id,
                    text=response_text,
                    channel="telegram",
                    metadata={"chat_id": str(chat_id)},
                )
                await self.send(out)

        except Exception as e:
            logger.exception("[Telegram] Voice processing error: %s", e)
            await update.message.reply_text(f"🎤 語音處理失敗: {e}")

    async def _handle_command(self, update, context) -> None:
        """Handle commands routed through Gateway."""
        if not self._check_auth(update):
            return

        chat_id = update.effective_chat.id
        msg = InboundMessage.from_telegram(
            update.to_dict(),
            chat_id=chat_id,
        )

        try:
            # Show typing indicator
            if ChatAction:
                await context.bot.send_chat_action(
                    chat_id=chat_id, action=ChatAction.TYPING)

            typing_task = asyncio.create_task(
                self._keep_typing(context.bot, chat_id))

            try:
                response = await process_message(msg)
            finally:
                typing_task.cancel()

            out = OutboundMessage(
                session_id=msg.session_id,
                text=response.text,
                channel="telegram",
                metadata={"chat_id": str(chat_id)},
            )
            await self.send(out)
        except Exception as e:
            logger.exception("[Telegram] Command error: %s", e)
            await update.message.reply_text(f"⚠️ 指令處理失敗: {e}")

    async def _handle_location(self, update, context) -> None:
        """Handle location messages: extract coordinates and process."""
        if not self._check_auth(update):
            return

        chat_id = update.effective_chat.id
        session_id = f"tg_{chat_id}"
        
        try:
            # Get location data
            location = update.message.location
            if not location:
                await update.message.reply_text("⚠️ 無法讀取位置訊息")
                return

            lat = location.latitude
            lon = location.longitude
            
            logger.info("[Telegram] Location received: lat=%s, lon=%s", lat, lon)
            
            # Create InboundMessage with location data
            pref = get_session_pref(session_id)
            msg = InboundMessage(
                channel="telegram",
                user_id=str(update.effective_user.id),
                session_id=session_id,
                text=f"📍 用戶位置：{lat}, {lon}",
                metadata={
                    "chat_id": str(chat_id),
                    "source": "location",
                    "location": {"lat": lat, "lon": lon},
                    "model_override": pref["model_override"] or "",
                    "output_mode": pref["output_mode"],
                },
            )

            # Show typing
            if ChatAction:
                await context.bot.send_chat_action(
                    chat_id=chat_id, action=ChatAction.TYPING)

            # Process through Gateway
            typing_task = asyncio.create_task(
                self._keep_typing(context.bot, chat_id))

            try:
                response = await process_message(msg)
            finally:
                typing_task.cancel()

            # Send response
            out = OutboundMessage(
                session_id=session_id,
                text=response.text,
                channel="telegram",
                metadata={"chat_id": str(chat_id)},
            )
            await self.send(out)

        except Exception as e:
            logger.exception("[Telegram] Location processing error: %s", e)
            await update.message.reply_text(f"⚠️ 位置處理失敗: {e}")

    async def _handle_photo(self, update, context) -> None:
        """Handle photo messages: download and process."""
        if not self._check_auth(update):
            return

        chat_id = update.effective_chat.id
        session_id = f"tg_{chat_id}"

        try:
            # Get photo
            photos = update.message.photo
            if not photos:
                await update.message.reply_text("⚠️ 無法讀取圖片")
                return

            # Get the largest photo
            photo = photos[-1]
            
            # Download photo
            file = await context.bot.get_file(photo.file_id)
            import tempfile
            from pathlib import Path
            img_path = Path(tempfile.gettempdir()) / f"arcmind_photo/{photo.file_id}.jpg"
            img_path.parent.mkdir(exist_ok=True)
            await file.download_to_drive(str(img_path))

            logger.info("[Telegram] Photo received: %s (%d bytes)",
                        photo.file_id, photo.file_size or 0)

            # Create message with photo path
            pref = get_session_pref(session_id)
            msg = InboundMessage(
                channel="telegram",
                user_id=str(update.effective_user.id),
                session_id=session_id,
                text="📷 用戶發送了一張圖片",
                attachments=[{
                    "type": "photo",
                    "file_id": photo.file_id,
                    "path": str(img_path),
                }],
                metadata={
                    "chat_id": str(chat_id),
                    "source": "photo",
                    "model_override": pref["model_override"] or "",
                    "output_mode": pref["output_mode"],
                },
            )

            # Show typing
            if ChatAction:
                await context.bot.send_chat_action(
                    chat_id=chat_id, action=ChatAction.TYPING)

            # Process through Gateway
            typing_task = asyncio.create_task(
                self._keep_typing(context.bot, chat_id))

            try:
                response = await process_message(msg)
            finally:
                typing_task.cancel()

            # Send response
            out = OutboundMessage(
                session_id=session_id,
                text=response.text,
                channel="telegram",
                metadata={"chat_id": str(chat_id)},
            )
            await self.send(out)

        except Exception as e:
            logger.exception("[Telegram] Photo processing error: %s", e)
            await update.message.reply_text(f"⚠️ 圖片處理失敗: {e}")

    # ── /tools — Interactive Tool Discovery ─────────────────────────────

    async def _handle_tools_cmd(self, update, context) -> None:
        """Handle /tools — show tool category InlineKeyboard."""
        if not self._check_auth(update):
            return
        await self._send_tools_categories(update.message)

    async def _send_tools_categories(self, message_or_query, edit: bool = False) -> None:
        """Send the tool categories keyboard."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        buttons = []
        row = []
        for cat_name in _TOOL_CATEGORIES:
            row.append(InlineKeyboardButton(
                cat_name, callback_data=f"tools:cat:{cat_name}"
            ))
            if len(row) == 2:
                buttons.append(row)
                row = []
        if row:
            buttons.append(row)

        reply_markup = InlineKeyboardMarkup(buttons)
        text = (
            "🧩 *ArcMind 工具箱*\n\n"
            "選擇分類查看可用工具："
        )
        if edit:
            await message_or_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode="Markdown"
            )
        else:
            await message_or_query.reply_text(
                text, reply_markup=reply_markup, parse_mode="Markdown"
            )

    async def _handle_tools_callback(self, update, context) -> None:
        """Handle InlineKeyboard callbacks for tool browsing."""
        query = update.callback_query
        await query.answer()
        data = query.data  # e.g. "tools:cat:📂 檔案與系統" or "tools:detail:web_search"

        if data == "tools:back":
            # Back to categories
            await self._send_tools_categories(query, edit=True)
            return

        if data.startswith("tools:cat:"):
            cat_name = data[len("tools:cat:"):]
            tool_names = _TOOL_CATEGORIES.get(cat_name, [])
            if not tool_names:
                await query.edit_message_text(f"分類 '{cat_name}' 沒有工具。")
                return

            # Load descriptions from tools_registry.json
            registry = self._load_tools_registry()

            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            buttons = []
            for tn in tool_names:
                desc = ""
                if tn in registry.get("skills", {}):
                    desc = registry["skills"][tn].get("description", "")[:25]
                elif tn in registry.get("tools", {}):
                    desc = registry["tools"][tn].get("description", "")[:25]
                label = f"{tn}"
                if desc:
                    label = f"{tn} — {desc}"
                buttons.append([InlineKeyboardButton(
                    label, callback_data=f"tools:detail:{tn}"
                )])

            buttons.append([InlineKeyboardButton(
                "↩️ 返回分類", callback_data="tools:back"
            )])

            reply_markup = InlineKeyboardMarkup(buttons)
            await query.edit_message_text(
                f"{cat_name}\n\n點選工具查看用法：",
                reply_markup=reply_markup,
            )
            return

        if data.startswith("tools:detail:"):
            tool_name = data[len("tools:detail:"):]
            registry = self._load_tools_registry()

            info = (registry.get("skills", {}).get(tool_name)
                    or registry.get("tools", {}).get(tool_name))

            if not info:
                text = f"❓ 找不到工具 `{tool_name}` 的詳細資訊。"
            else:
                desc = info.get("description", "無描述")
                usage = info.get("usage", "無用法")
                actions = info.get("actions", [])
                setup = info.get("setup", "")

                lines = [f"🔧 *{tool_name}*", f"{desc}", ""]
                if actions:
                    lines.append(f"📋 操作: {', '.join(actions)}")
                lines.append(f"\n💡 用法:\n`{usage}`")
                if setup:
                    lines.append(f"\n⚙️ 設定: {setup}")
                lines.append("\n💬 直接告訴我你想做什麼，我會自動選擇工具！")
                text = "\n".join(lines)

            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            buttons = [[InlineKeyboardButton(
                "↩️ 返回分類", callback_data="tools:back"
            )]]
            reply_markup = InlineKeyboardMarkup(buttons)
            try:
                await query.edit_message_text(
                    text, reply_markup=reply_markup, parse_mode="Markdown"
                )
            except Exception:
                # Markdown parse error fallback
                await query.edit_message_text(
                    text, reply_markup=reply_markup
                )

    @staticmethod
    def _load_tools_registry() -> dict:
        """Load tools_registry.json."""
        import json
        from pathlib import Path
        reg_path = Path(__file__).parent.parent / "config" / "tools_registry.json"
        try:
            return json.loads(reg_path.read_text(encoding="utf-8"))
        except Exception:
            return {}



    async def _keep_typing(self, bot, chat_id: int) -> None:
        """Periodically send typing action so it doesn't expire (~5s limit)."""
        try:
            while True:
                await asyncio.sleep(4)
                if ChatAction:
                    await bot.send_chat_action(
                        chat_id=chat_id, action=ChatAction.TYPING)
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    def _check_auth(self, update) -> bool:
        """Check if the chat is authorized."""
        if not update or not update.effective_chat:
            return False
            
        incoming_id = str(update.effective_chat.id)
        
        if not self.allowed_chat_id:
            logger.warning("[Telegram] Auth DENIED: No allowed_chat_id configured. Set TELEGRAM_CHAT_ID to allow access. Rejected chat_id=%s", incoming_id)
            return False  # Fail-closed: deny all when no whitelist configured
            
        allowed = str(self.allowed_chat_id)
        if incoming_id == allowed:
            return True
            
        logger.warning("[Telegram] Auth REJECTED: incoming chat_id=%s, allowed=%s", incoming_id, allowed)
        return False
