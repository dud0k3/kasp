"""Only fixed events and server-generated request metadata go to container logs."""

import json
import logging
import os
import time
import uuid


# Save the original output before the launcher redirects stdout/stderr.
PUBLIC_STREAM = os.fdopen(os.dup(1), "w", buffering=1)


class SafeFormatter(logging.Formatter):
    def format(self, record):
        # Deliberately ignore message, args, extra, exc_info and stack_info.
        # An exception can contain the full request, so masking a few keys is insufficient.
        level = record.levelname if record.levelname in {
            "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"
        } else "UNKNOWN"
        return json.dumps({"event": "runtime_log", "level": level})


def emit(event, **fields):
    PUBLIC_STREAM.write(json.dumps({"event": event, **fields}, separators=(",", ":")) + "\n")
    PUBLIC_STREAM.flush()


def silence_raw_output():
    # Also cover print(), native extensions and unhandled worker tracebacks.
    # The safe logging handler and audit events use PUBLIC_STREAM instead.
    with open(os.devnull, "w") as null:
        os.dup2(null.fileno(), 1)
        os.dup2(null.fileno(), 2)


class AuditMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        routes = {"/v1/chat/completions": "chat", "/v1/completions": "completion"}
        endpoint = routes.get(scope.get("path"))
        if endpoint is None:
            return await self.app(scope, receive, send)
        request_id = uuid.uuid4().hex
        start = time.perf_counter()
        status = 500
        emit("request_started", request_id=request_id, endpoint=endpoint)

        async def safe_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, safe_send)
        finally:
            emit("request_finished", request_id=request_id, endpoint=endpoint,
                 status=status, duration_ms=round((time.perf_counter() - start) * 1000, 2))
