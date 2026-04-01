from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from exchange_money_bot.config import settings
from exchange_money_bot.models import Base


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_conn, _connection_record) -> None:
    if dbapi_conn.__class__.__module__.startswith("sqlite3"):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _asyncpg_connect_args(url: str) -> dict:
    # Supabase transaction pooler (PgBouncer) cannot use asyncpg's prepared statement cache.
    if "pooler.supabase.com" in url or ":6543/" in url:
        return {"statement_cache_size": 0}
    return {}


engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args=_asyncpg_connect_args(settings.database_url),
)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _add_listings_channel_message_id_column(connection: Connection) -> None:
    """SQLite/Postgres: add column if missing (create_all does not alter existing tables)."""
    insp = inspect(connection)
    if "sell_offers" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("sell_offers")}
    if "listings_channel_message_id" in cols:
        return
    dialect = connection.dialect.name
    if dialect == "sqlite":
        connection.execute(
            text("ALTER TABLE sell_offers ADD COLUMN listings_channel_message_id BIGINT")
        )
    elif dialect in ("postgresql", "postgres"):
        connection.execute(
            text("ALTER TABLE sell_offers ADD COLUMN listings_channel_message_id BIGINT")
        )


def _add_sell_offer_description_column(connection: Connection) -> None:
    insp = inspect(connection)
    if "sell_offers" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("sell_offers")}
    if "description" in cols:
        return
    dialect = connection.dialect.name
    if dialect == "sqlite":
        connection.execute(text("ALTER TABLE sell_offers ADD COLUMN description VARCHAR(200)"))
    elif dialect in ("postgresql", "postgres"):
        connection.execute(text("ALTER TABLE sell_offers ADD COLUMN description VARCHAR(200)"))


def _add_sell_offer_payment_methods_column(connection: Connection) -> None:
    insp = inspect(connection)
    if "sell_offers" not in insp.get_table_names():
        return
    cols = {c["name"] for c in insp.get_columns("sell_offers")}
    if "payment_methods" in cols:
        return
    dialect = connection.dialect.name
    if dialect == "sqlite":
        connection.execute(text("ALTER TABLE sell_offers ADD COLUMN payment_methods TEXT"))
    elif dialect in ("postgresql", "postgres"):
        connection.execute(
            text("ALTER TABLE sell_offers ADD COLUMN payment_methods JSONB")
        )


async def init_db() -> None:
    if settings.database_url.startswith("sqlite"):
        from pathlib import Path

        Path("data").mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_listings_channel_message_id_column)
        await conn.run_sync(_add_sell_offer_description_column)
        await conn.run_sync(_add_sell_offer_payment_methods_column)
