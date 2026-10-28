"""Pluggable asynchronous image/video provider contracts.

The OpenAI implementation uses the official SDK. A configured key alone is insufficient:
execution also needs an allow-listed model and administrator-supplied pricing. CI uses MockMedia.
"""

import base64
import json
from dataclasses import dataclass, field
from typing import Protocol

from openai import AsyncOpenAI, OpenAIError

from ..config import Settings


class MediaError(Exception):
    def __init__(self, kind: str, message: str):
        self.kind = kind
        super().__init__(message)


@dataclass
class Capabilities:
    provider: str
    configured: bool
    image_models: list[str] = field(default_factory=list)
    video_models: list[str] = field(default_factory=list)
    image_operations: list[str] = field(default_factory=list)
    video_operations: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class Submitted:
    provider_job_id: str | None
    status: str
    data: bytes | None = None
    extension: str | None = None
    usage: dict = field(default_factory=dict)


class MediaProvider(Protocol):
    def capabilities(self) -> Capabilities: ...
    def estimate(self, kind: str, model: str, request: dict) -> float: ...
    async def submit(self, kind: str, model: str, operation: str, request: dict) -> Submitted: ...
    async def status(self, kind: str, provider_job_id: str) -> Submitted: ...
    async def cancel(self, kind: str, provider_job_id: str) -> bool: ...


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class OpenAIMedia:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.client = (
            AsyncOpenAI(api_key=settings.openai_media_api_key)
            if settings.openai_media_api_key
            else None
        )
        try:
            self.pricing = json.loads(settings.media_pricing_json)
        except ValueError:
            self.pricing = {}

    def capabilities(self) -> Capabilities:
        configured = bool(self.client)
        return Capabilities(
            provider="openai",
            configured=configured,
            image_models=_csv(self.settings.openai_image_models) if configured else [],
            video_models=_csv(self.settings.openai_video_models) if configured else [],
            image_operations=["generate", "edit"] if configured else [],
            video_operations=["generate", "status", "cancel"] if configured else [],
            note=(
                "Configured. Account entitlement is verified when an administrator performs an authorized job."
                if configured
                else "Unavailable: configure a server-side OpenAI media key. No credential is sent to the browser."
            ),
        )

    def estimate(self, kind: str, model: str, request: dict) -> float:
        if model not in (
            _csv(self.settings.openai_image_models)
            if kind == "image"
            else _csv(self.settings.openai_video_models)
        ):
            raise MediaError("unsupported", f"{model} is not enabled for {kind} generation")
        row = self.pricing.get(model)
        if not isinstance(row, dict):
            raise MediaError(
                "pricing_unknown", f"Validated pricing is required before {model} can run"
            )
        if kind == "image":
            unit = row.get(
                f"{request.get('quality', 'medium')}:{request.get('size', '1024x1024')}"
            ) or row.get("per_image_usd")
            count = int(request.get("variants", 1))
        else:
            unit = row.get("per_second_usd")
            count = int(request.get("duration_seconds", 0))
        if unit is None:
            raise MediaError(
                "pricing_unknown", f"Validated pricing does not cover this {kind} request"
            )
        return round(float(unit) * count, 6)

    async def submit(self, kind: str, model: str, operation: str, request: dict) -> Submitted:
        if not self.client:
            raise MediaError("unavailable", "OpenAI media is not configured")
        try:
            if kind == "image":
                if operation == "edit":
                    source = request.get("_source_bytes")
                    if not source:
                        raise MediaError("invalid", "Image editing needs a reference image")
                    response = await self.client.images.edit(
                        model=model,
                        image=source,
                        prompt=request["prompt"],
                        size=request.get("size", "1024x1024"),
                        quality=request.get("quality", "medium"),
                        background=request.get("background", "auto"),
                        n=int(request.get("variants", 1)),
                    )
                else:
                    response = await self.client.images.generate(
                        model=model,
                        prompt=request["prompt"],
                        size=request.get("size", "1024x1024"),
                        quality=request.get("quality", "medium"),
                        background=request.get("background", "auto"),
                        n=int(request.get("variants", 1)),
                    )
                images = [
                    base64.b64decode(item.b64_json) for item in response.data if item.b64_json
                ]
                if not images:
                    raise MediaError("provider", "OpenAI returned no image data")
                return Submitted(None, "completed", images[0], "png", {"variants": len(images)})
            if operation != "generate":
                raise MediaError("unsupported", f"Unsupported video operation: {operation}")
            kwargs = {
                "model": model,
                "prompt": request["prompt"],
                "seconds": str(request["duration_seconds"]),
                "size": request["size"],
            }
            if request.get("reference_asset"):
                kwargs["input_reference"] = request["_source_bytes"]
            video = await self.client.videos.create(**kwargs)
            return Submitted(video.id, getattr(video, "status", "queued"))
        except MediaError:
            raise
        except OpenAIError as exc:
            raise MediaError("provider", str(exc)[:400]) from exc

    async def status(self, kind: str, provider_job_id: str) -> Submitted:
        if kind != "video" or not self.client:
            raise MediaError("unsupported", "Only configured video jobs are asynchronous")
        try:
            video = await self.client.videos.retrieve(provider_job_id)
            state = getattr(video, "status", "unknown")
            if state == "completed":
                response = await self.client.videos.download_content(provider_job_id)
                return Submitted(provider_job_id, state, response.read(), "mp4")
            return Submitted(provider_job_id, state)
        except OpenAIError as exc:
            raise MediaError("provider", str(exc)[:400]) from exc

    async def cancel(self, kind: str, provider_job_id: str) -> bool:
        if kind != "video" or not self.client:
            return False
        try:
            await self.client.videos.delete(provider_job_id)
            return True
        except OpenAIError as exc:
            raise MediaError("provider", str(exc)[:400]) from exc


class MockMedia:
    """Deterministic provider fixture for CI; it never reaches an external API."""

    def capabilities(self) -> Capabilities:
        return Capabilities(
            "mock", True, ["mock-image"], [], ["generate", "edit"], [], "Development fixture"
        )

    def estimate(self, kind: str, model: str, request: dict) -> float:
        return round(0.01 * int(request.get("variants", 1)), 6)

    async def submit(self, kind: str, model: str, operation: str, request: dict) -> Submitted:
        if kind == "video":
            raise MediaError("unavailable", "Mock video generation is disabled")
        return Submitted(None, "completed", b"\x89PNG\r\n\x1a\nmock-image", "png", {"variants": 1})

    async def status(self, kind: str, provider_job_id: str) -> Submitted:
        raise MediaError("unavailable", "No asynchronous mock jobs")

    async def cancel(self, kind: str, provider_job_id: str) -> bool:
        return False


def providers(settings: Settings) -> dict[str, MediaProvider]:
    return {"openai": OpenAIMedia(settings)}
