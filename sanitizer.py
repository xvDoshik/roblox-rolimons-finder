from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

ROBLOX_ITEM_ID_MAX = 9_999_999_999_999_999
DIGITS_ONLY = re.compile(r"^\d{1,16}$")
ROLIMONS_ITEM_URL = re.compile(
    r"^https?://(?:www\.)?rolimons\.com/item/(\d{1,16})/?$",
    re.IGNORECASE,
)

INJECTION_PATTERNS = (
    re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", re.MULTILINE),
    re.compile(r"(?i)(<\s*script|javascript\s*:|vbscript\s*:|data\s*:text/html)"),
    re.compile(r"(?i)(on\w+\s*=|<\s*iframe|<\s*object|<\s*embed|<\s*svg)"),
    re.compile(
        r"(?i)(\bunion\b.+\bselect\b|\bdrop\b.+\btable\b|\binsert\b.+\binto\b|'\s*or\s*'1'\s*=\s*'1)"
    ),
    re.compile(r"(?i)(\$\{\{|<%|<\?=|\{\{|\}\}|;\s*--|\bor\b\s+1\s*=\s*1)"),
    re.compile(r"(?i)(\|\||&&|\$\(|\`\s*|\bcurl\b|\bwget\b|\b/bin/sh\b)"),
    re.compile(r"(?i)(\.\./|\.\.\\|%2e%2e|%00|%0a|%0d)"),
    re.compile(r"(?i)(\beval\s*\(|\bexec\s*\(|\bsystem\s*\()"),
)

SAFE_TOKEN = re.compile(r"^[a-zA-Z0-9_\-]+$")
SAFE_PATH = re.compile(r"^/[a-zA-Z0-9_./\-]*$")


class SanitizerError(ValueError):
    pass


class InputSanitizer:
    @staticmethod
    def normalize_text(value: str) -> str:
        if not isinstance(value, str):
            raise SanitizerError("invalid text input")
        text = unicodedata.normalize("NFKC", value).strip()
        if not text:
            raise SanitizerError("empty input")
        InputSanitizer.reject_injection(text)
        return text

    @staticmethod
    def reject_injection(value: str) -> None:
        for pattern in INJECTION_PATTERNS:
            if pattern.search(value):
                raise SanitizerError("forbidden input pattern")

    @staticmethod
    def safe_path(path: str) -> str:
        if not path or len(path) > 512:
            raise SanitizerError("invalid path")
        if not SAFE_PATH.match(path):
            raise SanitizerError("invalid path")
        if ".." in path or "//" in path.replace("://", ""):
            raise SanitizerError("invalid path")
        InputSanitizer.reject_injection(path)
        return path

    @staticmethod
    def safe_enum(value: str, allowed: tuple[str, ...]) -> str:
        token = InputSanitizer.normalize_text(value)
        if not SAFE_TOKEN.match(token):
            raise SanitizerError("invalid token")
        if token not in allowed:
            raise SanitizerError("invalid token")
        return token

    @staticmethod
    def safe_item_id(value: int) -> int:
        if not isinstance(value, int):
            raise SanitizerError("invalid item id")
        if value <= 0 or value > ROBLOX_ITEM_ID_MAX:
            raise SanitizerError("invalid item id")
        return value


class ItemInputSanitizer:
    @staticmethod
    def sanitize_token(raw: str) -> str:
        text = InputSanitizer.normalize_text(raw)
        if len(text) > 256:
            raise SanitizerError("item entry too long")

        digits = DIGITS_ONLY.match(text)
        if digits:
            item_id = int(digits.group(0))
            InputSanitizer.safe_item_id(item_id)
            return str(item_id)

        url_match = ROLIMONS_ITEM_URL.match(text)
        if url_match:
            item_id = int(url_match.group(1))
            InputSanitizer.safe_item_id(item_id)
            return str(item_id)

        if "rolimons.com" in text.lower():
            parsed = urlparse(text)
            if parsed.scheme not in {"http", "https"}:
                raise SanitizerError("invalid item url")
            if parsed.netloc.lower() not in {"rolimons.com", "www.rolimons.com"}:
                raise SanitizerError("invalid item url")
            if parsed.query or parsed.fragment:
                raise SanitizerError("invalid item url")
            segments = [part for part in parsed.path.split("/") if part]
            if len(segments) != 2 or segments[0].lower() != "item":
                raise SanitizerError("invalid item url")
            if not DIGITS_ONLY.match(segments[1]):
                raise SanitizerError("invalid item url")
            item_id = int(segments[1])
            InputSanitizer.safe_item_id(item_id)
            return str(item_id)

        raise SanitizerError("invalid item id or url")

    @staticmethod
    def sanitize_many(values: list[str]) -> list[str]:
        cleaned = [ItemInputSanitizer.sanitize_token(value) for value in values]
        if len(set(cleaned)) < 2:
            raise SanitizerError("need at least 2 unique items")
        return cleaned


class OutputSanitizer:
    DISPLAY_NAME = re.compile(r"^[\w \-'.]{1,64}$", re.UNICODE)

    @staticmethod
    def safe_display_name(value: str | None) -> str | None:
        if not value or not isinstance(value, str):
            return None
        text = unicodedata.normalize("NFKC", value).strip()
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"[\x00-\x1f\x7f]", "", text)
        if not text or not OutputSanitizer.DISPLAY_NAME.match(text):
            return None
        return text[:64]


class HeaderSanitizer:
    @staticmethod
    def require_json_content_type(content_type: str | None) -> None:
        if not content_type:
            raise SanitizerError("content-type required")
        base = content_type.split(";", 1)[0].strip().lower()
        if base != "application/json":
            raise SanitizerError("content-type must be application/json")
        InputSanitizer.reject_injection(content_type)

    @staticmethod
    def safe_client_ip(value: str) -> str:
        text = value.strip()[:64]
        if not text:
            return "unknown"
        if not re.fullmatch(r"[0-9a-fA-F:.]+", text):
            raise SanitizerError("invalid client ip")
        return text
