from __future__ import annotations

import pytest

from fastgpt_ocr_adapter.config import Settings


def test_defaults_select_mineru() -> None:
    settings = Settings.from_env()
    assert settings.provider == "mineru"
    assert settings.api_profile == "mineru-api-v3"
    assert settings.provider_version == "3.4.4"
    assert settings.max_concurrent_requests == 1
    assert settings.max_queued_requests == 1


def test_marker_environment_is_loaded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FASTGPT_OCR_PROVIDER", "MARKER")
    monkeypatch.setenv("FASTGPT_OCR_API_PROFILE", "MARKER-SERVER-V2")
    monkeypatch.setenv("FASTGPT_OCR_PROVIDER_VERSION", "2.0.0")
    monkeypatch.setenv("MARKER_BASE_URL", "http://marker:8000/")
    monkeypatch.setenv("MARKER_FORCE_OCR", "yes")
    monkeypatch.setenv("MARKER_MODE", "FAST")
    monkeypatch.setenv("FASTGPT_OCR_MAX_QUEUED_REQUESTS", "0")
    settings = Settings.from_env()
    assert settings.provider == "marker"
    assert settings.api_profile == "marker-server-v2"
    assert settings.marker_base_url == "http://marker:8000"
    assert settings.marker_force_ocr is True
    assert settings.marker_mode == "fast"
    assert settings.max_queued_requests == 0


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("FASTGPT_OCR_REQUIRE_AUTH", "maybe"),
        ("FASTGPT_OCR_MAX_FILE_BYTES", "0"),
        ("FASTGPT_OCR_MAX_PAGES", "abc"),
        ("FASTGPT_OCR_MAX_CONCURRENT_REQUESTS", "0"),
        ("FASTGPT_OCR_MAX_QUEUED_REQUESTS", "-1"),
        ("FASTGPT_OCR_TIMEOUT_SECONDS", "0"),
        ("FASTGPT_OCR_QUEUE_TIMEOUT_SECONDS", "nope"),
        ("MARKER_MODE", "turbo"),
        ("MINERU_BASE_URL", "file:///tmp/mineru"),
    ],
)
def test_invalid_environment_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        Settings.from_env()


@pytest.mark.parametrize(
    "name",
    ["FASTGPT_OCR_TIMEOUT_SECONDS", "FASTGPT_OCR_QUEUE_TIMEOUT_SECONDS"],
)
def test_timeouts_must_be_below_fastgpt_limit(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    monkeypatch.setenv(name, "600")
    with pytest.raises(ValueError, match="600"):
        Settings.from_env()
