-- Postgres / Neon / Supabase (and similar). Adjust database name as needed.
-- Internal user id (user_id) + Telegram's numeric id (telegram_id).

CREATE TABLE IF NOT EXISTS users (
    id         BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL UNIQUE,
    username    TEXT,
    first_name  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_telegram_id ON users (telegram_id);

CREATE TABLE IF NOT EXISTS sell_offers (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             BIGINT NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    telegram_id         BIGINT NOT NULL,
    telegram_username   TEXT,
    seller_display_name TEXT NOT NULL,
    amount              BIGINT NOT NULL,
    currency            VARCHAR(8) NOT NULL,
    description         VARCHAR(200),
    listings_channel_message_id BIGINT,
    payment_methods     JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sell_offers_user_id ON sell_offers (user_id);
CREATE INDEX IF NOT EXISTS idx_sell_offers_telegram_id ON sell_offers (telegram_id);
CREATE INDEX IF NOT EXISTS idx_sell_offers_currency ON sell_offers (currency);
CREATE INDEX IF NOT EXISTS idx_sell_offers_created_at ON sell_offers (created_at);
