import httpx

from ..config import Settings


class EngineeringUnavailable(RuntimeError):
    pass


async def extract(settings: Settings, prompt: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{settings.engineering_service_url.rstrip('/')}/v1/requirements/extract",
                params={"prompt": prompt},
            )
    except httpx.HTTPError as exc:
        raise EngineeringUnavailable("Engineering requirements service is unavailable") from exc
    if response.status_code != 200:
        detail = response.json().get("detail", "Requirement extraction failed")
        raise ValueError(str(detail))
    return response.json()


async def generate(settings: Settings, body: dict) -> dict:
    try:
        timeout = httpx.Timeout(settings.engineering_job_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{settings.engineering_service_url.rstrip('/')}/v1/generate",
                json=body,
            )
    except httpx.HTTPError as exc:
        raise EngineeringUnavailable("Engineering CAD worker is unavailable") from exc
    if response.status_code == 422:
        detail = response.json().get("detail", "Invalid engineering geometry")
        raise ValueError(str(detail))
    if response.status_code != 200:
        raise EngineeringUnavailable("Engineering CAD worker failed safely")
    return response.json()
