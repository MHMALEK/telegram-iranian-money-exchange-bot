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
    """If set with enforce flag, users must be members of this chat. Defaults to listings channel when unset."""

    telegram_enforce_channel_membership: bool = False
    """When True and a membership channel id is available, block bot use for non-members."""

    telegram_channel_invite_url: Optional[str] = None
    """https://t.me/… link shown on «join channel» and «open listings» prompts."""

    def effective_membership_channel_id(self) -> Optional[str]:
        return self.telegram_membership_channel_id or self.telegram_listings_channel_id

    def membership_gate_active(self) -> bool:
        return self.telegram_enforce_channel_membership and bool(
            self.effective_membership_channel_id()
        )

    def effective_listings_channel_open_url(self) -> Optional[str]:
        """Public URL for «open channel» buttons: invite link, else https://t.me/name if id is @name."""
        if self.telegram_channel_invite_url:
            s = self.telegram_channel_invite_url.strip()
            if s:
                return s
        cid = (self.telegram_listings_channel_id or "").strip()
        if cid.startswith("@"):
            u = cid[1:].strip()
            if u:
                return f"https://t.me/{u}"
        return None


settings = Settings()
