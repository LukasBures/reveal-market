from __future__ import annotations

from typing import Any


class DummyStreamer:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


async def noop() -> None:
    return None
