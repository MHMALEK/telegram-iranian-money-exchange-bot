# IND biometrics slot monitor

Polls the [IND online appointment planner](https://oap.ind.nl/oap/en/#/BIO) for **biometrics (BIO)** slots at Haarlem, Amsterdam, or Utrecht, and alerts you when a slot opens **before your cutoff date**.

No browser or DigiD login is required for checking — it uses the same public API as the website.

## Quick start

```bash
cd ind-bio-monitor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# edit .env (Telegram optional, AUTO_BOOK off by default)
python run_once.py
```

Run every 15 minutes:

```bash
python run_loop.py
```

Or use cron (macOS/Linux):

```cron
*/15 * * * * cd /path/to/ind-bio-monitor && .venv/bin/python run_once.py >> logs/check.log 2>&1
```

## Configuration

| Variable | Meaning |
|----------|---------|
| `CUTOFF_DATE` | Only care about slots **before** this date (default `2026-07-07`) |
| `CHECK_INTERVAL_MINUTES` | Loop interval (default `15`) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | Optional push alerts |
| `AUTO_BOOK` | `true` to reserve + book the earliest matching slot automatically |

When `AUTO_BOOK=true`, also set `EMAIL`, `PHONE`, `BIRTH_DATE`, `FIRST_NAME`, `LAST_NAME`, and either `V_NUMBER` or `BSN`.

## Current availability (checked live)

As of setup time there were **no** BIO slots before 2026-07-07 at Haarlem, Amsterdam, or Utrecht. The monitor is useful when someone cancels and an earlier slot appears.

## If you already have an appointment

IND may reject a second booking if your V-number/BSN already has an appointment. You may need to **cancel or reschedule** your 7 July slot first (use the link in your confirmation email).

## Be a good citizen

- Polling every 15 minutes is reasonable for a personal tool; avoid sub-minute loops.
- Keep your BSN and V-number in `.env` only — never commit them.
- Automating government booking systems may conflict with IND terms; use at your own risk.
