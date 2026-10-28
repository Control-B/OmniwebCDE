"""Serves generated-app previews on their own origin.

Run separately from the control plane:  uvicorn app.preview_server:app --port 43230

Previews never share an origin with Omniweb itself. With subdomains on, every project gets its
own origin (<token>.preview.<host>); otherwise previews are served under /p/<token>/. Static files
come from bundles built in the sandbox, and /api/* is proxied to the project's sandboxed API over
its Unix socket. No Omniweb cookies, tokens, or provider credentials ever reach this server.
"""

import json
import mimetypes
import re
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, PlainTextResponse

from .builder import preview
from .config import get_settings

settings = get_settings()
app = FastAPI(title="Omniweb preview", docs_url=None, redoc_url=None, openapi_url=None)
TOKEN = re.compile(r"^[0-9a-f]{16}$")
HOST = re.compile(r"^([0-9a-f]{16})\.preview\.")
HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "cookie",
    "set-cookie",
    "content-length",
}
MAX_BODY = 5_000_000
BRIDGE = (Path(__file__).parent / "builder" / "assets" / "preview-bridge.js").read_text()


def csp() -> str:
    ancestors = " ".join(settings.allowed_frontend_origins)
    return (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; "
        f"font-src 'self' data:; connect-src 'self'; frame-ancestors {ancestors}; base-uri 'self'; form-action 'self'; object-src 'none'"
    )


def harden(response: Response) -> Response:
    response.headers["Content-Security-Policy"] = csp()
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    response.headers.setdefault("Cache-Control", "no-cache")
    return response


def locate(request: Request) -> tuple[str | None, str, str]:
    """Returns (token, path inside the preview, URL prefix)."""
    host = request.headers.get("host", "")
    path = request.url.path
    match = HOST.match(host)
    if match:
        return match.group(1), path, ""
    parts = path.split("/", 3)
    if len(parts) >= 3 and parts[1] == "p" and TOKEN.match(parts[2]):
        return parts[2], "/" + (parts[3] if len(parts) > 3 else ""), f"/p/{parts[2]}"
    return None, path, ""


def not_found(message: str = "Preview not found") -> Response:
    return harden(PlainTextResponse(message, status_code=404))


@app.api_route("/{rest:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def serve(request: Request, rest: str) -> Response:
    token, path, prefix = locate(request)
    if not token or not TOKEN.match(token):
        return not_found()
    if prefix and path == "/" and not request.url.path.endswith("/"):
        return Response(status_code=308, headers={"Location": f"{prefix}/"})
    if path == "/__omniweb/bridge.js":
        return harden(Response(BRIDGE, media_type="text/javascript"))
    api = re.match(r"^/(?:mobile/)?(api(?:/.*)?)$", path)
    if api:
        return await proxy(request, token, "/" + api.group(1))
    if request.method not in {"GET", "HEAD"}:
        return harden(PlainTextResponse("Method not allowed", status_code=405))
    root = preview.current(settings, token)
    if not root:
        return not_found("This preview has not been built yet")
    kind = "mobile" if path == "/mobile" or path.startswith("/mobile/") else "web"
    if kind == "web" and not (root / "web").is_dir() and (root / "mobile").is_dir():
        return Response(status_code=307, headers={"Location": f"{prefix}/mobile/"})
    if path == "/mobile":
        return Response(status_code=308, headers={"Location": f"{prefix}/mobile/"})
    bundle = root / kind
    relative = path.removeprefix("/mobile").lstrip("/") if kind == "mobile" else path.lstrip("/")
    target = (bundle / relative).resolve() if relative else bundle / "index.html"
    if not target.is_relative_to(bundle.resolve()) or not target.is_file():
        target = bundle / "index.html"
        if "." in relative.rsplit("/", 1)[-1]:
            return not_found("File not found")
    if not target.is_file():
        return not_found()
    if target.name == "index.html":
        return harden(Response(inject(target.read_text(), prefix, kind), media_type="text/html"))
    media = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    response = FileResponse(target, media_type=media)
    if "/assets/" in str(target):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return harden(response)


def inject(html: str, prefix: str, kind: str) -> str:
    origins = json.dumps(settings.allowed_frontend_origins).replace("'", "&#39;")
    tag = f'<script src="{prefix}/__omniweb/bridge.js" data-origins=\'{origins}\' data-kind="{kind}"></script>'
    return html.replace("</head>", tag + "</head>", 1) if "</head>" in html else tag + html


async def proxy(request: Request, token: str, path: str) -> Response:
    socket = preview.run_dir(settings, token) / "api.sock"
    if not socket.exists():
        return harden(
            Response(
                json.dumps(
                    {"detail": "This app's API is not running. Rebuild the project to start it."}
                ),
                status_code=503,
                media_type="application/json",
            )
        )
    body = await request.body()
    if len(body) > MAX_BODY:
        return harden(PlainTextResponse("Request too large", status_code=413))
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP}
    transport = httpx.AsyncHTTPTransport(uds=str(socket))
    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://preview-api", timeout=30
        ) as client:
            upstream = await client.request(
                request.method, path, params=request.query_params, content=body, headers=headers
            )
    except httpx.HTTPError:
        return harden(
            Response(
                json.dumps({"detail": "This app's API did not respond"}),
                status_code=502,
                media_type="application/json",
            )
        )
    response_headers = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() not in HOP and k.lower() != "content-encoding"
    }
    return harden(
        Response(upstream.content, status_code=upstream.status_code, headers=response_headers)
    )
