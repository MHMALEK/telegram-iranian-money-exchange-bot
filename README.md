# Exchange money bot

A **personal**, **non‑commercial** Telegram bot. The goal is modest: make it a bit simpler for **people in Iran** to find each other for **ریال ↔ euro / US dollar** deals—posting offers, browsing a small catalog, and seeing rough **ریالی equivalents** from public rate snapshots.

It does **not** move money, hold funds, or vet counterparties. You’re always responsible for who you trust and how you settle.

---

### What it does (high level)

- **Sign‑up / consent** flow in Persian  
- **Sell flow**: post an amount in EUR or USD; optional publish to a **listings channel** (bot must be admin there)  
- **Buy / browse** helpers and **channel membership** gate when configured  
- Small **FastAPI** app alongside the bot (e.g. for integrations); **SQLite** or **Postgres** via `DATABASE_URL`

---

### Run locally

Requires **Python 3.9+**.

```bash
cp .env.example .env   # fill in TELEGRAM_BOT_TOKEN and the rest
pip install -e ".[dev]"
python run_bot.py      # Telegram bot
# optional: python run_api.py   # FastAPI on :8000
```

Docker starts **both** the API and the bot (see `scripts/docker-entrypoint.sh`).

Tests: `pytest`

---

### Deploy

The repo includes a **Dockerfile** and a **GitHub Actions** workflow (`.github/workflows/deploy.yml`) that builds, pushes to **GHCR**, and **SSH‑deploys** to a VPS. The workflow runs `docker run` with `-e` so values are not interpolated into the shell script (safe for passwords and URLs).

#### Required (Secrets)

| Name | Purpose |
|------|---------|
| `VM_HOST`, `VM_USER`, `VM_SSH_KEY` | SSH into the deployment server |
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `DATABASE_URL` | Async SQLAlchemy URL (e.g. Postgres); includes credentials |
| **One channel id** | Set `TELEGRAM_LISTINGS_CHANNEL_ID` and/or `TELEGRAM_MEMBERSHIP_CHANNEL_ID` (see below). The deploy script requires at least one to be non‑empty. |

**Channel ids — how they interact**

- **`TELEGRAM_LISTINGS_CHANNEL_ID`** — Where sell offers are posted and where the «open channel» / listings CTA should point when a public URL can be resolved.
- **`TELEGRAM_MEMBERSHIP_CHANNEL_ID`** — If set, membership is checked against this chat **instead of** the listings channel. If **`TELEGRAM_LISTINGS_CHANNEL_ID` is unset**, the membership channel id is also used to **post listings** and to resolve the open link (single‑channel setup).
- Setting **only** `TELEGRAM_MEMBERSHIP_CHANNEL_ID` does **not** change the listings target when `TELEGRAM_LISTINGS_CHANNEL_ID` is already set (they are different chats in that case). The bot message link is always for the **listings** channel.


#### Optional (Secrets)

Omit any you do not use; optional ones are only passed into the container when non‑empty (except the two channel ids, which are always passed through and may be empty if the other is set).

| Name | Purpose |
|------|---------|
| `TELEGRAM_MEMBERSHIP_CHANNEL_ID` | Override which channel is used for the membership gate; see table above |
| `TELEGRAM_MEMBERSHIP_GROUP_ID` | Optional group/supergroup; with a channel id, user passes if member of **either** (OR) |
| `TELEGRAM_CHANNEL_INVITE_URL` | Join/open link for the **listings** side of the bot (required for a clear button when the channel is private) |
| `TELEGRAM_MEMBERSHIP_GROUP_INVITE_URL` | Invite link for the membership group button |

#### Optional (Variables)

| Name | Purpose |
|------|---------|
| `TELEGRAM_DISABLE_MEMBERSHIP_GATE` | `true` only for dev‑style deploys |
| `API_BASE_URL` | If the bot should call the HTTP API after upsert |
| `IRR_RATES_TTL_SECONDS`, `IRR_USD_JSON_URL`, `IRR_EUR_JSON_URL` | Spot‑rate cache / JSON sources |

#### Secrets vs variables

Use **Secrets** for tokens, `DATABASE_URL`, and invite links. Use **Variables** for non‑sensitive toggles and URLs. Local parity: `.env.example` / `.env` use the same names.

---

### Disclaimer

**Not** financial, legal, or tax advice. Rates shown are indicative only. This project is a hobby; use it at your own risk.
