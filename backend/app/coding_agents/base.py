from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any


class CodingAgentAdapter(ABC):
    @abstractmethod
    async def initialize(self) -> dict[str, Any]: ...

    @abstractmethod
    async def check_health(self) -> bool: ...

    @abstractmethod
    async def start_session(self, working_directory: str, model: str | None = None) -> str: ...

    @abstractmethod
    async def send_instruction(self, session_id: str, instruction: str) -> str: ...

    @abstractmethod
    async def stream_events(self, session_id: str) -> AsyncIterator[dict[str, Any]]: ...

    @abstractmethod
    async def request_approval(self, request_id: int, decision: str) -> None: ...

    @abstractmethod
    async def cancel_session(self, session_id: str) -> None: ...

    @abstractmethod
    async def get_status(self, session_id: str) -> dict[str, Any]: ...

    @abstractmethod
    async def terminate(self) -> None: ...
