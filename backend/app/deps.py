"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from .db import get_session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_user_id(x_user_id: Annotated[str | None, Header()] = None) -> str:
    """First release identifies users with a plain header (01 §4)."""
    return x_user_id or "default"


UserIdDep = Annotated[str, Depends(get_user_id)]
