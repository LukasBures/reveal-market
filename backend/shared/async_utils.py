from __future__ import annotations

import inspect
from collections.abc import Awaitable
from typing import TypeVar, cast

T = TypeVar("T")


async def resolve_awaitable(value: Awaitable[T] | T) -> T:  # noqa: UP047
    """Resolve a value that may or may not be awaitable.

    Redis async clients sometimes return ``Awaitable[T] | T`` depending on
    whether a pipeline is in use.  This helper normalises both cases into a
    single ``await``-able call.
    """
    if inspect.isawaitable(value):
        return cast(T, await value)
    return cast(T, value)
