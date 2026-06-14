from __future__ import annotations

import asyncio
import logging

from app.bot import DirectorBot
from app.config import load_settings
from app.google_sheets import GoogleSheetsService
from app.logging_config import configure_logging
from app.reporting import ReportService


async def async_main() -> None:
    configure_logging()
    settings = load_settings()
    sheets = GoogleSheetsService(settings)
    reports = ReportService(sheets)
    bot = DirectorBot(settings, reports)
    await bot.run()


def main() -> None:
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        logging.getLogger(__name__).info("Бот остановлен вручную")


if __name__ == "__main__":
    main()
