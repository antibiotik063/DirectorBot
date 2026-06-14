from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    telegram_bot_token: str
    google_drive_file_id: str | None
    google_service_account_json: str
    owner_telegram_id: int | None
    owner_telegram_username: str | None
    timezone: str
    report_time: str

    @property
    def service_account_info(self) -> dict:
        value = self.google_service_account_json.strip()
        candidate = Path(value)
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
        return json.loads(value)


def load_settings() -> Settings:
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    service_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()

    if not token:
        raise ValueError("Не задан TELEGRAM_BOT_TOKEN")
    if not service_json:
        raise ValueError("Не задан GOOGLE_SERVICE_ACCOUNT_JSON")

    owner_id = os.getenv("OWNER_TELEGRAM_ID", "").strip()
    owner_username = os.getenv("OWNER_TELEGRAM_USERNAME", "").strip().lstrip("@")

    return Settings(
        telegram_bot_token=token,
        google_drive_file_id=os.getenv("GOOGLE_DRIVE_FILE_ID", "").strip() or None,
        google_service_account_json=service_json,
        owner_telegram_id=int(owner_id) if owner_id else None,
        owner_telegram_username=owner_username or None,
        timezone=os.getenv("TIMEZONE", "Europe/Samara").strip() or "Europe/Samara",
        report_time=os.getenv("REPORT_TIME", "09:00").strip() or "09:00",
    )
