from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DEFAULT_DESKS: dict[str, str] = {
    "6b425ff9f87de136a36b813cccf26e23": "IND Haarlem",
    "AM": "IND Amsterdam",
    "fa24ccf0acbc76a7793765937eaee440": "Expatcenter Utrecht",
}

PRODUCT_KEY = "BIO"
BASE_URL = "https://oap.ind.nl/oap/api"


def _desk_map() -> dict[str, str]:
    raw = os.getenv("DESKS", "").strip()
    if not raw:
        return DEFAULT_DESKS
    result: dict[str, str] = {}
    for key in raw.split(","):
        key = key.strip()
        if key:
            result[key] = DEFAULT_DESKS.get(key, key)
    return result


@dataclass(frozen=True)
class Settings:
    cutoff_date: str
    interval_minutes: int
    persons: int
    locale: str
    desks: dict[str, str]
    state_dir: Path
    telegram_token: str | None
    telegram_chat_id: str | None
    auto_book: bool
    email: str | None
    phone: str | None
    birth_date: str | None
    first_name: str | None
    last_name: str | None
    v_number: str | None
    bsn: str | None


def load_settings() -> Settings:
    return Settings(
        cutoff_date=os.getenv("CUTOFF_DATE", "2026-07-07"),
        interval_minutes=int(os.getenv("CHECK_INTERVAL_MINUTES", "15")),
        persons=int(os.getenv("PERSONS", "1")),
        locale=os.getenv("LOCALE", "en"),
        desks=_desk_map(),
        state_dir=Path(os.getenv("STATE_DIR", "./state")),
        telegram_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID") or None,
        auto_book=os.getenv("AUTO_BOOK", "false").lower() in {"1", "true", "yes"},
        email=os.getenv("EMAIL") or None,
        phone=os.getenv("PHONE") or None,
        birth_date=os.getenv("BIRTH_DATE") or None,
        first_name=os.getenv("FIRST_NAME") or None,
        last_name=os.getenv("LAST_NAME") or None,
        v_number=os.getenv("V_NUMBER") or None,
        bsn=os.getenv("BSN") or None,
    )
