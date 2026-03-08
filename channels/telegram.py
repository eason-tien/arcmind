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

        app = Application.builder().token(self.token).build()

        # Register handlers
        app.add_handler(CommandHandler("start", self._handle_start))
        app.add_handler(CommandHandler("model", self._handle_model_cmd))
        app.add_handler(CommandHandler("mode", self._handle_mode_cmd))
        app.add_handler(CallbackQueryHandler(
            self._handle_callback, pattern=r"^model:"))
        app.add_handler(CallbackQueryHandler(
            self._handle_callback, pattern=r"^mode:"))
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
            if app.updater.running:
                await app.updater.stop()
            await app.stop()
            await app.shutdown()
            self._running = False

    async def stop(self) -> None:
        """Stop Telegram polling."""
        self._running = False
        logger.info("[Telegram] Stopping bot...")

    async def send(self, message: OutboundMessage) -> bool:
        """Send a message back to Telegram."""
        if not self._app or not self._app.bot:
            return False

        chat_id = message.metadata.get("chat_id", self.allowed_chat_id)
        if not chat_id:
            logger.warning("[Telegram] No chat_id for outbound message")
            return False

        try:
            await self._app.bot.send_message(
                chat_id=int(chat_id),
                text=message.text,
                parse_mode="Markdown",
            )
            return True
        except Exception as e:
            logger.error("[Telegram] Send failed: %s", e)
            # Retry without markdown
            try:
                await self._app.bot.send_message(
                    chat_id=int(chat_id),
                    text=message.text,
                )
                return True
            except Exception as e2:
                logger.error("[Telegram] Send retry failed: %s", e2)
                return False

    # ── Telegram Handlers ───────────────────────────────────────────────

    async def _handle_start(self, update, context) -> None:
        """Handle /start command."""
        pref = get_session_pref(f"tg_{update.effective_chat.id}")
        model = pref["model_override"] or "自動"
        mode = pref["output_mode"]
        await update.message.reply_text(
            "🧠 *ArcMind v0.3.0*\n"
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
            finally:
                typing_task.cancel()

            # Send response
            out = OutboundMessage(
                session_id=msg.session_id,
                text=response.text,
                channel="telegram",
                metadata={"chat_id": str(chat_id)},
            )
            await self.send(out)

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
        if not self.allowed_chat_id:
            return True  # No restriction
        return str(update.effective_chat.id) == str(self.allowed_chat_id)
