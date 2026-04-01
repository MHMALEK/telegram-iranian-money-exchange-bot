from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: Optional[str] = None
    database_url: str = "sqlite+aiosqlite:///./data/app.db"
    """Async SQLAlchemy URL, e.g. postgresql+asyncpg://... or sqlite+aiosqlite:///./data/app.db"""

    api_base_url: Optional[str] = None
    """If set, the bot pings the API after upsert (optional loose coupling)."""

    telegram_listings_channel_id: Optional[str] = None
    """Channel chat id (@username or -100…) where new sell offers are posted. Bot must be admin."""

    telegram_membership_channel_id: Optional[str] = None
    """Optional: different channel for membership checks (defaults to listings when unset). If listings id is unset, this id is also used to post listings and to resolve open-channel links (single-channel setup)."""

    telegram_membership_group_id: Optional[str] = None
    """Optional group or supergroup chat id (@username or -100…). Bot must be able to get_chat_member. Used with channel id as OR: user passes if member of any configured chat."""

    telegram_disable_membership_gate: bool = False
    """If True, skip membership checks (local/dev only). When False, a configured group id and/or channel id (see effective_*) enables the gate."""

    telegram_channel_invite_url: Optional[str] = None
    """https://t.me/… link shown on «join channel» and «open listings» prompts."""

    telegram_membership_group_invite_url: Optional[str] = None
    """Optional invite link for the membership group when «join group» is shown."""

    irr_rates_ttl_seconds: int = 300
    """Cache TTL for USD/EUR→rial JSON snapshots (see irr_fiat_rates)."""

    irr_usd_json_url: Optional[str] = None
    """Override USD/RL JSON URL; default is margani/pricedb TGJU mirror."""

    irr_eur_json_url: Optional[str] = None
    """Override EUR JSON URL; default is margani/pricedb TGJU mirror."""

    def effective_membership_channel_id(self) -> Optional[str]:
        return self.telegram_membership_channel_id or self.telegram_listings_channel_id

    def effective_listings_channel_id(self) -> Optional[str]:
        """Chat where listings are posted and where «open channel» should point. Listings id wins; else membership id."""
        lid = (self.telegram_listings_channel_id or "").strip()
        if lid:
            return lid
        mid = (self.telegram_membership_channel_id or "").strip()
        return mid or None

    def effective_membership_group_id(self) -> Optional[str]:
        s = (self.telegram_membership_group_id or "").strip()
        return s or None

    def membership_gate_active(self) -> bool:
        if self.telegram_disable_membership_gate:
            return False
        return bool(self.effective_membership_group_id()) or bool(
            self.effective_membership_channel_id()
        )

    def effective_listings_channel_open_url(self) -> Optional[str]:
        """Public URL for «open channel» buttons: invite link, else https://t.me/name if id is @name."""
        if self.telegram_channel_invite_url:
            s = self.telegram_channel_invite_url.strip()
            if s:
                return s
        cid = (self.effective_listings_channel_id() or "").strip()
        if cid.startswith("@"):
            u = cid[1:].strip()
            if u:
                return f"https://t.me/{u}"
        return None


settings = Settings()
