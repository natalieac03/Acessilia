"""Base abstract class for LLM clients used in the bot."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseLLMClient(ABC):

    @abstractmethod
    async def send_message(self, text: str, **kwargs: Any) -> str:
        raise NotImplementedError

    async def reset_session(self) -> None:
        return None

    async def close(self) -> None:
        return None
