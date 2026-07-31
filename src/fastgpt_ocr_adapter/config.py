from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value is not None and value.strip() else default


def _bool_env(name: str, default: bool) -> bool:
    value = _env(name, str(default)).lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


def _int_env(name: str, default: int, *, minimum: int) -> int:
    value = _env(name, str(default))
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return parsed


def _float_env(name: str, default: float) -> float:
    value = _env(name, str(default))
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be greater than zero")
    return parsed


def _base_url(name: str, default: str) -> str:
    value = _env(name, default).rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{name} must be an http or https URL")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    provider: str = "mineru"
    api_profile: str = "mineru-api-v3"
    provider_version: str = "3.4.4"
    auth_token: str = ""
    require_auth: bool = True
    timeout_seconds: float = 540.0
    max_file_bytes: int = 50 * 1024 * 1024
    max_pages: int = 500
    max_concurrent_requests: int = 1
    max_queued_requests: int = 1
    queue_timeout_seconds: float = 60.0
    mineru_base_url: str = "http://host.docker.internal:8000"
    marker_base_url: str = "http://host.docker.internal:8000"
    marker_force_ocr: bool = False
    marker_mode: str = "balanced"
    marker_auth_token: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        settings = cls(
            provider=_env("FASTGPT_OCR_PROVIDER", defaults.provider).lower(),
            api_profile=_env("FASTGPT_OCR_API_PROFILE", defaults.api_profile).lower(),
            provider_version=_env(
                "FASTGPT_OCR_PROVIDER_VERSION", defaults.provider_version
            ),
            auth_token=_env("FASTGPT_OCR_AUTH_TOKEN", ""),
            require_auth=_bool_env("FASTGPT_OCR_REQUIRE_AUTH", defaults.require_auth),
            timeout_seconds=_float_env(
                "FASTGPT_OCR_TIMEOUT_SECONDS", defaults.timeout_seconds
            ),
            max_file_bytes=_int_env(
                "FASTGPT_OCR_MAX_FILE_BYTES", defaults.max_file_bytes, minimum=1
            ),
            max_pages=_int_env("FASTGPT_OCR_MAX_PAGES", defaults.max_pages, minimum=1),
            max_concurrent_requests=_int_env(
                "FASTGPT_OCR_MAX_CONCURRENT_REQUESTS",
                defaults.max_concurrent_requests,
                minimum=1,
            ),
            max_queued_requests=_int_env(
                "FASTGPT_OCR_MAX_QUEUED_REQUESTS",
                defaults.max_queued_requests,
                minimum=0,
            ),
            queue_timeout_seconds=_float_env(
                "FASTGPT_OCR_QUEUE_TIMEOUT_SECONDS", defaults.queue_timeout_seconds
            ),
            mineru_base_url=_base_url("MINERU_BASE_URL", defaults.mineru_base_url),
            marker_base_url=_base_url("MARKER_BASE_URL", defaults.marker_base_url),
            marker_force_ocr=_bool_env(
                "MARKER_FORCE_OCR", defaults.marker_force_ocr
            ),
            marker_mode=_env("MARKER_MODE", defaults.marker_mode).lower(),
            marker_auth_token=_env("MARKER_AUTH_TOKEN", ""),
        )
        if settings.timeout_seconds >= 600:
            raise ValueError(
                "FASTGPT_OCR_TIMEOUT_SECONDS must be below FastGPT's 600 second timeout"
            )
        if settings.queue_timeout_seconds >= 600:
            raise ValueError(
                "FASTGPT_OCR_QUEUE_TIMEOUT_SECONDS must be below FastGPT's 600 second timeout"
            )
        if settings.marker_mode not in {"balanced", "fast"}:
            raise ValueError("MARKER_MODE must be balanced or fast")
        return settings
