from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from exchange_money_bot.database import async_session_factory, init_db
from exchange_money_bot.services import users as user_service


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Exchange Money Bot API", lifespan=lifespan)


class UserOut(BaseModel):
    id: int
    telegram_id: int
    username: Optional[str]
    first_name: Optional[str]

    model_config = {"from_attributes": True}


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/users/by-telegram/{telegram_id}", response_model=UserOut)
async def get_user(
    telegram_id: int,
    session: AsyncSession = Depends(get_db),
):
    user = await user_service.get_user_by_telegram(session, telegram_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@app.delete("/users/by-telegram/{telegram_id}", status_code=204)
async def delete_user(
    telegram_id: int,
    session: AsyncSession = Depends(get_db),
):
    deleted = await user_service.delete_user_by_telegram(session, telegram_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="User not found")
