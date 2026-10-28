import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from typing import Any

from .base import CodingAgentAdapter


class CodexAppServerAdapter(CodingAgentAdapter):
    """Structured stdio client for the documented Codex app-server JSON-RPC API."""

    def __init__(self, executable: str = "codex"):
        self.executable = executable
        self.process: asyncio.subprocess.Process | None = None
        self.reader_task: asyncio.Task | None = None
        self.request_id = 0
        self.pending: dict[int, asyncio.Future] = {}
        self.events: dict[str, asyncio.Queue] = defaultdict(asyncio.Queue)
        self.turns: dict[str, str] = {}

    async def initialize(self) -> dict[str, Any]:
        if self.process:
            return {"status": "already_initialized"}
        self.process = await asyncio.create_subprocess_exec(
            self.executable,
            "app-server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self.reader_task = asyncio.create_task(self._read_messages())
        result = await self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "omniweb-cde",
                    "title": "Omniweb CDE",
                    "version": "0.1.0",
                }
            },
        )
        await self._notify("initialized", {})
        return result

    async def check_health(self) -> bool:
        return bool(self.process and self.process.returncode is None)

    async def start_session(self, working_directory: str, model: str | None = None) -> str:
        params: dict[str, Any] = {"cwd": working_directory}
        if model:
            # The model must come from model/list; Omniweb does not invent model IDs.
            catalog = await self._request("model/list", {"limit": 100, "includeHidden": False})
            valid = {item["id"] for item in catalog.get("data", [])}
            if model not in valid:
                raise ValueError("Requested model is not in the Codex model catalog")
            params["model"] = model
        result = await self._request("thread/start", params)
        return str(result["thread"]["id"])

    async def send_instruction(self, session_id: str, instruction: str) -> str:
        result = await self._request(
            "turn/start",
            {
                "threadId": session_id,
                "input": [{"type": "text", "text": instruction}],
            },
        )
        turn_id = str(result["turn"]["id"])
        self.turns[session_id] = turn_id
        return turn_id

    async def stream_events(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        queue = self.events[session_id]
        while True:
            message = await queue.get()
            yield message
            if message.get("method") == "turn/completed":
                return

    async def request_approval(self, request_id: int, decision: str) -> None:
        allowed = {"accept", "acceptForSession", "decline", "cancel"}
        if decision not in allowed:
            raise ValueError("Unsupported approval decision")
        await self._response(request_id, {"decision": decision})

    async def cancel_session(self, session_id: str) -> None:
        turn_id = self.turns.get(session_id)
        if turn_id:
            await self._request("turn/interrupt", {"threadId": session_id, "turnId": turn_id})

    async def get_status(self, session_id: str) -> dict[str, Any]:
        result = await self._request(
            "thread/read", {"threadId": session_id, "includeTurns": False}
        )
        return result["thread"]

    async def terminate(self) -> None:
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()
        if self.reader_task:
            self.reader_task.cancel()
        for future in self.pending.values():
            if not future.done():
                future.set_exception(RuntimeError("Codex app-server terminated"))

    async def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.request_id += 1
        request_id = self.request_id
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        await self._write({"method": method, "id": request_id, "params": params})
        return await asyncio.wait_for(future, timeout=30)

    async def _notify(self, method: str, params: dict[str, Any]) -> None:
        await self._write({"method": method, "params": params})

    async def _response(self, request_id: int, result: dict[str, Any]) -> None:
        await self._write({"id": request_id, "result": result})

    async def _write(self, message: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise RuntimeError("Codex app-server is not initialized")
        self.process.stdin.write((json.dumps(message) + "\n").encode())
        await self.process.stdin.drain()

    async def _read_messages(self) -> None:
        assert self.process and self.process.stdout
        while line := await self.process.stdout.readline():
            message = json.loads(line)
            if "id" in message and ("result" in message or "error" in message):
                future = self.pending.pop(message["id"], None)
                if future:
                    if "error" in message:
                        future.set_exception(RuntimeError(message["error"].get("message", "Codex error")))
                    else:
                        future.set_result(message["result"])
                continue
            params = message.get("params", {})
            thread_id = params.get("threadId") or params.get("thread", {}).get("id")
            if thread_id:
                await self.events[str(thread_id)].put(message)
