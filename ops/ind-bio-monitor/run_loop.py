#!/usr/bin/env python3
import time

from ind_monitor.config import load_settings
from ind_monitor.monitor import _notify, run_check


def main() -> None:
    settings = load_settings()
    interval = max(1, settings.interval_minutes) * 60
    print(f"Polling every {settings.interval_minutes} minutes for BIO slots before {settings.cutoff_date}")
    _notify(
        settings,
        "🟢 <b>IND biometrics monitor started</b>\n"
        f"Checking every {settings.interval_minutes} min for slots before {settings.cutoff_date}.\n"
        f"Locations: Haarlem, Amsterdam, Utrecht\n"
        f"Auto-book: {'on' if settings.auto_book else 'off'}",
    )
    while True:
        try:
            run_check(settings)
        except Exception as exc:  # noqa: BLE001 - keep loop alive
            msg = f"⚠️ IND monitor check failed: {exc}"
            print(msg)
            _notify(settings, msg)
        time.sleep(interval)


if __name__ == "__main__":
    main()
