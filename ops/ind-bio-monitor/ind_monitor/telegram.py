from __future__ import annotations

import httpx


def send_message(token: str, chat_id: str, text: str) -> None:
    response = httpx.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        timeout=20.0,
    )
    response.raise_for_status()
