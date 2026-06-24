"""
HTTP middleware for per-request observability.

`RequestContextMiddleware` is the canonical place where:
1. A `request_id` is chosen (incoming `X-Request-ID` header, or a new
   UUID hex). It is stashed in a `contextvars.ContextVar` so any
   `logger.info(...)` call down the stack automatically picks it up
   (via `JsonFormatter`).
2. The request's start time is captured for duration calculation.
3. Two structured log lines are emitted:
   - `request.start` (INFO) — emitted before the handler runs.
   - `request.end`   (INFO) — emitted after, with status_code +
     duration_ms.
   On uncaught exceptions, `request.error` (ERROR) is emitted and
   the exception is re-raised so FastAPI's normal 500 handler runs.
4. The `X-Request-ID` response header echoes the request id back to
   the client (useful for support tickets, debugging, etc.).
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response

from app.core.logging import new_request_id, request_id_var

log = logging.getLogger("app.request")


def install_request_context_middleware(app: FastAPI) -> None:
    """Register the request-context middleware on a FastAPI app.

    Starlette's `BaseHTTPMiddleware` is used (not the newer `app.middleware`
    decorator) because it gives us a stable async hook that works with
    both the live ASGI server and the in-process ASGI test client used
    by the pytest smoke + coverage suite.
    """
    app.add_middleware(_RequestContextMiddleware)


class _RequestContextMiddleware:
    """ASGI middleware implementation (Starlette-compatible)."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(
        self, scope: dict[str, Any], receive: Callable[..., Any], send: Callable[..., Any]
    ) -> None:
        if scope["type"] != "http":
            # Lifespan / websocket: no request context.
            await self.app(scope, receive, send)
            return

        # Pick or generate request_id.
        headers = dict(scope.get("headers") or [])
        incoming = headers.get(b"x-request-id")
        if incoming is not None:
            try:
                rid = incoming.decode("ascii", errors="ignore").strip() or new_request_id()
            except Exception:
                rid = new_request_id()
        else:
            rid = new_request_id()

        token = request_id_var.set(rid)
        start = time.perf_counter()
        method = scope.get("method", "?")
        path = scope.get("path", "?")

        log.info(
            "request.start",
            extra={
                "event": "request.start",
                "method": method,
                "path": path,
                "request_id": rid,
            },
        )

        status_holder: dict[str, int] = {"status": 500}
        rid_header_bytes = b"x-request-id"
        rid_header_value = rid.encode("ascii", errors="ignore")

        async def send_with_status_capture(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = int(message.get("status", 500))
                # Echo X-Request-ID back to the client. Mutating headers
                # at this point is allowed (the start message hasn't
                # been sent on the wire yet).
                headers = list(message.get("headers") or [])
                headers.append((rid_header_bytes, rid_header_value))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_status_capture)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            log.exception(
                "request.error",
                extra={
                    "event": "request.error",
                    "method": method,
                    "path": path,
                    "request_id": rid,
                    "status_code": 500,
                    "duration_ms": duration_ms,
                    "error_type": type(exc).__name__,
                },
            )
            request_id_var.reset(token)
            raise

        duration_ms = round((time.perf_counter() - start) * 1000, 2)
        log.info(
            "request.end",
            extra={
                "event": "request.end",
                "method": method,
                "path": path,
                "request_id": rid,
                "status_code": status_holder["status"],
                "duration_ms": duration_ms,
            },
        )
        request_id_var.reset(token)


# Convenience wrapper for tests that want to call the request handler
# directly with an in-process ASGI client.
async def run_request_with_context(
    request: Request,
    handler: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Run a handler inside the request_id context. Used by tests."""
    rid = request.headers.get("x-request-id") or new_request_id()
    token = request_id_var.set(rid)
    try:
        return await handler(request)
    finally:
        request_id_var.reset(token)
