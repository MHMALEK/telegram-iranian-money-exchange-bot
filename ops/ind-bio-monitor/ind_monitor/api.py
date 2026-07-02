from __future__ import annotations

import json
from typing import Any

import httpx

from .config import BASE_URL, PRODUCT_KEY


class IndOapClient:
    def __init__(self, locale: str = "en") -> None:
        self.locale = locale
        self._client = httpx.Client(
            base_url=BASE_URL,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "oap-locale": locale,
            },
            timeout=30.0,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> IndOapClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @staticmethod
    def _parse_payload(text: str) -> dict[str, Any]:
        # IND prefixes JSON with )]}' (anti-XSSI).
        cleaned = text.removeprefix(")]}',")
        return json.loads(cleaned)

    def get_slots(self, desk_key: str, persons: int = 1) -> list[dict[str, Any]]:
        response = self._client.get(
            f"/desks/{desk_key}/slots",
            params={"productKey": PRODUCT_KEY, "persons": str(persons)},
        )
        response.raise_for_status()
        payload = self._parse_payload(response.text)
        return payload.get("data") or []

    def reserve_slot(self, desk_key: str, slot: dict[str, Any]) -> None:
        response = self._client.post(
            f"/desks/{PRODUCT_KEY}/{desk_key}/slots/{slot['key']}",
            json=slot,
        )
        response.raise_for_status()

    def book_appointment(self, desk_key: str, slot: dict[str, Any], appointment: dict[str, Any]) -> dict[str, Any]:
        body = {
            "bookableSlot": slot,
            "appointment": appointment,
        }
        response = self._client.post(
            f"/desks/{desk_key}/appointments",
            content=json.dumps(body),
        )
        response.raise_for_status()
        return self._parse_payload(response.text)
