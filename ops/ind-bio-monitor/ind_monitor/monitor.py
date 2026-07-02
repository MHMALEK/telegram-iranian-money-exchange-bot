from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .api import IndOapClient
from .config import PRODUCT_KEY, Settings
from .telegram import send_message


def _slot_key(slot: dict[str, Any], desk_key: str) -> str:
    return f"{desk_key}|{slot['date']}|{slot['startTime']}|{slot['key']}"


def _format_slot(name: str, slot: dict[str, Any]) -> str:
    return f"• <b>{name}</b> — {slot['date']} {slot['startTime']}-{slot['endTime']}"


def _load_seen(path: Path) -> set[str]:
    if not path.exists():
        return set()
    data = json.loads(path.read_text())
    return set(data.get("seen", []))


def _save_seen(path: Path, seen: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"seen": sorted(seen)}, indent=2))


def _notify(settings: Settings, text: str) -> None:
    print(text.replace("<b>", "").replace("</b>", ""))
    if settings.telegram_token and settings.telegram_chat_id:
        send_message(settings.telegram_token, settings.telegram_chat_id, text)


def _validate_booking_settings(settings: Settings) -> None:
    missing = [
        name
        for name, value in {
            "EMAIL": settings.email,
            "PHONE": settings.phone,
            "BIRTH_DATE": settings.birth_date,
            "FIRST_NAME": settings.first_name,
            "LAST_NAME": settings.last_name,
        }.items()
        if not value
    ]
    if not settings.v_number and not settings.bsn:
        missing.append("V_NUMBER or BSN")
    if missing:
        raise RuntimeError(f"AUTO_BOOK=true but missing: {', '.join(missing)}")


def _build_appointment(settings: Settings, slot: dict[str, Any]) -> dict[str, Any]:
    customer: dict[str, Any] = {
        "firstName": settings.first_name,
        "lastName": settings.last_name,
    }
    if settings.v_number:
        customer["vNumber"] = settings.v_number
    if settings.bsn:
        customer["bsn"] = settings.bsn

    return {
        "productKey": PRODUCT_KEY,
        "date": slot["date"],
        "startTime": slot["startTime"],
        "endTime": slot["endTime"],
        "email": settings.email,
        "phone": settings.phone,
        "language": settings.locale,
        "birthDate": settings.birth_date,
        "customers": [customer],
    }


def run_check(settings: Settings) -> int:
    cutoff = settings.cutoff_date
    seen_path = settings.state_dir / "seen-slots.json"
    seen = _load_seen(seen_path)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    matches: list[tuple[str, str, dict[str, Any]]] = []
    summaries: list[str] = []

    with IndOapClient(locale=settings.locale) as client:
        if settings.auto_book:
            _validate_booking_settings(settings)
            candidates: list[tuple[str, str, dict[str, Any]]] = []
            for desk_key, desk_name in settings.desks.items():
                slots = client.get_slots(desk_key, settings.persons)
                for slot in slots:
                    if slot.get("date", "") < cutoff:
                        candidates.append((desk_key, desk_name, slot))
            if candidates:
                desk_key, desk_name, slot = sorted(
                    candidates, key=lambda item: (item[2]["date"], item[2]["startTime"])
                )[0]
                appointment = _build_appointment(settings, slot)
                client.reserve_slot(desk_key, slot)
                client.book_appointment(desk_key, slot, appointment)
                _notify(
                    settings,
                    "✅ <b>Booked IND biometrics appointment</b>\n"
                    + _format_slot(desk_name, slot)
                    + f"\n\nConfirmation email sent to {settings.email}.",
                )
                seen.add(_slot_key(slot, desk_key))
                _save_seen(seen_path, seen)
                return 0

        for desk_key, desk_name in settings.desks.items():
            slots = client.get_slots(desk_key, settings.persons)
            before = [s for s in slots if s.get("date", "") < cutoff]
            earliest = slots[0]["date"] if slots else "none"
            summaries.append(f"{desk_name}: {len(before)} before {cutoff} (earliest overall: {earliest})")

            for slot in before:
                key = _slot_key(slot, desk_key)
                if key not in seen:
                    matches.append((desk_key, desk_name, slot))

    header = f"IND BIO check ({now})\n" + "\n".join(f"• {line}" for line in summaries)

    if not matches:
        print(f"✅ No new slots before {cutoff}.\n{header}")
        return 0

    body = "🆕 <b>New slots before your cutoff</b>\n" + "\n".join(
        _format_slot(name, slot) for _, name, slot in matches
    )
    _notify(settings, body + "\n\n" + header)

    for desk_key, _, slot in matches:
        seen.add(_slot_key(slot, desk_key))
    _save_seen(seen_path, seen)
    return 0
