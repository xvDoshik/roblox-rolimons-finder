from __future__ import annotations

import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from sanitizer import HeaderSanitizer, InputSanitizer, ItemInputSanitizer, SanitizerError


@dataclass(frozen=True)
class SecurityPolicy:
    hourly_limit: int = 1000
    burst_limit: int = 40
    burst_window_seconds: float = 10.0
    block_seconds: float = 120.0
    max_body_bytes: int = 32_768
    max_concurrent_intersect: int = 2
    max_items_per_search: int = 25
    max_item_token_length: int = 256
    request_timeout_seconds: float = 90.0


@dataclass
class ClientState:
    events: deque[float] = field(default_factory=deque)
    blocked_until: float = 0.0
    intersect_active: int = 0


class RateLimitStore:
    def __init__(self, policy: SecurityPolicy) -> None:
        self._policy = policy
        self._clients: dict[str, ClientState] = {}
        self._lock = threading.Lock()

    def _state(self, client_key: str) -> ClientState:
        state = self._clients.get(client_key)
        if state is None:
            state = ClientState()
            self._clients[client_key] = state
        return state

    @staticmethod
    def _prune(state: ClientState, now: float, window: float) -> None:
        cutoff = now - window
        while state.events and state.events[0] < cutoff:
            state.events.popleft()

    def check(self, client_key: str) -> tuple[bool, str | None, int | None]:
        now = time.monotonic()
        with self._lock:
            state = self._state(client_key)
            if state.blocked_until > now:
                retry = int(state.blocked_until - now) + 1
                return False, "client temporarily blocked", retry

            self._prune(state, now, 3600.0)
            if len(state.events) >= self._policy.hourly_limit:
                state.blocked_until = now + self._policy.block_seconds
                return False, "hourly request limit exceeded", self._policy.block_seconds

            burst_cutoff = now - self._policy.burst_window_seconds
            burst_count = sum(1 for ts in state.events if ts >= burst_cutoff)
            if burst_count >= self._policy.burst_limit:
                state.blocked_until = now + self._policy.block_seconds
                return False, "burst limit exceeded", self._policy.block_seconds

            state.events.append(now)
            remaining = max(0, self._policy.hourly_limit - len(state.events))
            return True, None, remaining

    def acquire_intersect(self, client_key: str) -> bool:
        with self._lock:
            state = self._state(client_key)
            if state.intersect_active >= self._policy.max_concurrent_intersect:
                return False
            state.intersect_active += 1
            return True

    def release_intersect(self, client_key: str) -> None:
        with self._lock:
            state = self._clients.get(client_key)
            if state and state.intersect_active > 0:
                state.intersect_active -= 1


class ClientKeyResolver:
    @staticmethod
    def resolve(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            try:
                return HeaderSanitizer.safe_client_ip(forwarded.split(",")[0])
            except SanitizerError:
                return "unknown"
        if request.client and request.client.host:
            try:
                return HeaderSanitizer.safe_client_ip(request.client.host)
            except SanitizerError:
                return "unknown"
        return "unknown"


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, policy: SecurityPolicy | None = None) -> None:
        super().__init__(app)
        self._policy = policy or SecurityPolicy()
        self._store = RateLimitStore(self._policy)

    def _secure_json(
        self,
        payload: dict,
        status_code: int,
        extra_headers: dict[str, str] | None = None,
    ) -> JSONResponse:
        headers = extra_headers or {}
        response = JSONResponse(payload, status_code=status_code, headers=headers)
        self._apply_security_headers(response)
        return response

    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            path = InputSanitizer.safe_path(request.url.path)
        except SanitizerError:
            return self._secure_json({"detail": "forbidden"}, 403)

        query = str(request.url.query or "")
        if query:
            try:
                InputSanitizer.reject_injection(query)
            except SanitizerError:
                return self._secure_json({"detail": "forbidden"}, 403)

        if self._is_blocked_path(path):
            return self._secure_json({"detail": "forbidden"}, 403)

        if not self._allowed_method(request.method, path):
            return self._secure_json({"detail": "method not allowed"}, 405)

        if path == "/api/intersect" and request.method == "POST":
            try:
                HeaderSanitizer.require_json_content_type(request.headers.get("content-type"))
            except SanitizerError:
                return self._secure_json({"detail": "invalid content-type"}, 415)

        client_key = ClientKeyResolver.resolve(request)
        is_api = path.startswith("/api/")
        rate_limited = is_api and path not in {"/api/health", "/api/sources"}

        if rate_limited:
            allowed, reason, retry = self._store.check(client_key)
            if not allowed:
                return self._secure_json(
                    {"detail": reason},
                    429,
                    {"Retry-After": str(int(retry or 60))},
                )
            request.state.rate_remaining = retry

            if request.method in {"POST", "PUT", "PATCH"}:
                content_length = request.headers.get("content-length")
                if content_length and content_length.isdigit():
                    if int(content_length) > self._policy.max_body_bytes:
                        return self._secure_json({"detail": "payload too large"}, 413)

        intersect_slot = False
        if path == "/api/intersect" and request.method == "POST":
            if not self._store.acquire_intersect(client_key):
                return self._secure_json(
                    {"detail": "too many concurrent searches"},
                    429,
                    {"Retry-After": "5"},
                )
            intersect_slot = True

        try:
            response = await call_next(request)
        finally:
            if intersect_slot:
                self._store.release_intersect(client_key)

        self._apply_security_headers(response)
        if rate_limited and hasattr(request.state, "rate_remaining"):
            response.headers["X-RateLimit-Remaining"] = str(request.state.rate_remaining)
        return response

    @staticmethod
    def _is_blocked_path(path: str) -> bool:
        lowered = path.lower()
        blocked_fragments = ("/etc/", "/proc/", "/api/../", "\\")
        return any(fragment in lowered for fragment in blocked_fragments)

    @staticmethod
    def _allowed_method(method: str, path: str) -> bool:
        if path.startswith("/assets/"):
            return method == "GET"
        if path == "/":
            return method == "GET"
        if path.startswith("/api/"):
            return method in {"GET", "POST", "HEAD", "OPTIONS"}
        return method in {"GET", "HEAD", "OPTIONS"}

    @staticmethod
    def _apply_security_headers(response: Response) -> None:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' https: data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; script-src 'self'; connect-src 'self'",
        )
