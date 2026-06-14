from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.constants import ChatType
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from app.config import Settings
from app.reporting import ReportService

logger = logging.getLogger(__name__)


class DirectorBot:
    def __init__(self, settings: Settings, reports: ReportService) -> None:
        self.settings = settings
        self.reports = reports
        self.owner_chat_id = settings.owner_telegram_id
        self.scheduler = AsyncIOScheduler(timezone=settings.timezone)
        self.application: Application = ApplicationBuilder().token(settings.telegram_bot_token).build()
        self._register_handlers()

    def _register_handlers(self) -> None:
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("today", self.today))
        self.application.add_handler(CommandHandler("report", self.report))
        self.application.add_error_handler(self.on_error)

    async def run(self) -> None:
        self._configure_schedule()
        self.scheduler.start()
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling(drop_pending_updates=False)
        logger.info("Bot started")
        await asyncio.Event().wait()

    def _configure_schedule(self) -> None:
        hour, minute = self._parse_report_time(self.settings.report_time)
        self.scheduler.remove_all_jobs()
        self.scheduler.add_job(
            self._scheduled_send_report,
            "cron",
            hour=hour,
            minute=minute,
            timezone=self.settings.timezone,
            id="daily-report",
            replace_existing=True,
        )
        logger.info(
            "Daily report scheduled for %02d:%02d (%s)",
            hour,
            minute,
            self.settings.timezone,
        )

    def _parse_report_time(self, value: str) -> tuple[int, int]:
        hour_text, minute_text = value.split(":")
        return int(hour_text), int(minute_text)

    def _is_private_chat(self, update: Update) -> bool:
        chat = update.effective_chat
        return bool(chat and chat.type == ChatType.PRIVATE)

    def _is_authorized(self, update: Update) -> bool:
        if not self._is_private_chat(update):
            return False
        user = update.effective_user
        chat = update.effective_chat
        if chat and self.owner_chat_id is not None and chat.id == self.owner_chat_id:
            return True
        if self.settings.owner_telegram_username and user:
            return (user.username or "").lower() == self.settings.owner_telegram_username.lower()
        if self.owner_chat_id is None:
            return True
        return False

    async def _reject_if_unauthorized(self, update: Update) -> bool:
        if self._is_authorized(update):
            return False
        await update.effective_chat.send_message("Access to reports is allowed only for the club owner.")
        return True

    async def _send_current_report(self, chat_id: int) -> None:
        report = self.reports.build_report()
        await self.application.bot.send_message(chat_id=chat_id, text=report.text)

    async def _scheduled_send_report(self) -> None:
        if self.owner_chat_id is None:
            logger.warning("OWNER_TELEGRAM_ID is not set, skipping scheduled report")
            return

        try:
            await self._send_current_report(self.owner_chat_id)
            logger.info("Daily report sent to Telegram")
        except Exception:
            logger.exception("Failed to send daily report")

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_private_chat(update):
            return
        chat_id = update.effective_chat.id
        username = update.effective_user.username or "not-set"
        if self.settings.owner_telegram_username and username.lower() == self.settings.owner_telegram_username.lower():
            self.owner_chat_id = chat_id
            logger.info("Received owner chat_id @%s: %s", username, chat_id)
        await update.effective_chat.send_message(
            f"Telegram ID: {chat_id}\n"
            f"Username: @{username}\n\n"
            "Commands:\n"
            "/today - send the current report\n"
            "/report - send the current report\n"
            "/help - show commands"
        )

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._is_private_chat(update):
            return
        await update.effective_chat.send_message(
            "/start - show your Telegram ID\n"
            "/today - send the current report from sheet \"Кибер 2.0\"\n"
            "/report - send the current report from sheet \"Кибер 2.0\"\n"
            "/help - show commands"
        )

    async def today(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._reject_if_unauthorized(update):
            return
        await self._send_current_report(update.effective_chat.id)

    async def report(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._reject_if_unauthorized(update):
            return
        await self._send_current_report(update.effective_chat.id)

    async def on_error(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.exception("Telegram error: %s", context.error)
