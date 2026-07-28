from __future__ import annotations

import base64
from pathlib import Path

import pytest
from conftest import build_pdf
from fastapi.testclient import TestClient

from fastgpt_ocr_adapter.app import create_app
from fastgpt_ocr_adapter.config import Settings
from fastgpt_ocr_adapter.errors import (
    ProviderProcessingError,
    ProviderProtocolError,
    ProviderTimeout,
    ProviderUnavailable,
)
from fastgpt_ocr_adapter.gate import QueueFullError, QueueTimeoutError
from fastgpt_ocr_adapter.providers import ProviderHealth, ProviderResult

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\npayload").decode()
PNG_URI = f"data:image/png;base64,{PNG}"


class FakeProvider:
    name = "mineru"
    api_profile = "mineru-api-v3"
    version = "3.4.4"

    def __init__(
        self,
        *,
        result: ProviderResult | None = None,
        parse_error: Exception | None = None,
        health_error: Exception | None = None,
        health: ProviderHealth | None = None,
    ) -> None:
        self.result = result or ProviderResult("# parsed", {}, 200)
        self.parse_error = parse_error
        self.health_error = health_error
        self.health_result = health or ProviderHealth(
            "healthy", "3.4.4", "2", 200
        )
        self.closed = False
        self.received_path: Path | None = None

    async def parse(self, path: Path) -> ProviderResult:
        self.received_path = path
        if self.parse_error:
            raise self.parse_error
        return self.result

    async def health(self) -> ProviderHealth:
        if self.health_error:
            raise self.health_error
        return self.health_result

    async def close(self) -> None:
        self.closed = True


class FailingGate:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def __aenter__(self):
        raise self.error

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        del exc_type, exc_value, traceback


def client_for(
    provider: FakeProvider | None = None,
    **settings_overrides,
) -> tuple[TestClient, FakeProvider]:
    selected = provider or FakeProvider()
    values = {"auth_token": "secret", **settings_overrides}
    settings = Settings(**values)
    return TestClient(create_app(settings, selected)), selected


def upload(
    client: TestClient,
    content: bytes | None = None,
    *,
    content_type: str = "application/pdf",
    headers: dict[str, str] | None = None,
):
    return client.post(
        "/v2/parse/file",
        files={
            "file": (
                "sample.pdf",
                content if content is not None else build_pdf(),
                content_type,
            )
        },
        headers=(
            headers
            if headers is not None
            else {"Authorization": "Bearer secret"}
        ),
    )


def test_success_contract_and_temporary_file_cleanup() -> None:
    provider = FakeProvider(
        result=ProviderResult(
            "![image](images/picture.png)",
            {"picture.png": PNG_URI},
            200,
        )
    )
    client, provider = client_for(provider)
    with client:
        response = upload(client)
    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "",
        "pages": 1,
        "markdown": f"![image]({PNG_URI})",
    }
    assert response.headers["X-Request-ID"]
    assert provider.closed is True
    assert provider.received_path is not None
    assert not provider.received_path.exists()


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({}, 401),
        ({"Authorization": "Bearer wrong"}, 401),
        ({"Authorization": "Basic secret"}, 401),
        ({"Authorization": "Bearer secret"}, 200),
    ],
)
def test_bearer_authentication(headers: dict[str, str], expected: int) -> None:
    client, _ = client_for()
    with client:
        response = upload(client, headers=headers)
    assert response.status_code == expected


def test_authentication_can_be_disabled() -> None:
    client, _ = client_for(require_auth=False, auth_token="")
    with client:
        response = upload(client, headers={})
        ready = client.get("/health/ready")
    assert response.status_code == 200
    assert ready.status_code == 200
    assert ready.json()["auth_configured"] is True


def test_missing_auth_configuration_is_not_ready() -> None:
    settings = Settings(auth_token="")
    with TestClient(create_app(settings, FakeProvider())) as client:
        assert client.get("/health/live").status_code == 200
        ready = client.get("/health")
        response = upload(client)
    assert ready.status_code == 503
    assert ready.json()["auth_configured"] is False
    assert response.status_code == 503
    assert response.json()["error"] == "AUTH_NOT_CONFIGURED"


def test_health_reports_provider_profile_and_protocol() -> None:
    client, _ = client_for()
    with client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")
    assert live.json() == {
        "status": "alive",
        "adapter_version": "0.1.0",
        "provider": "mineru",
        "api_profile": "mineru-api-v3",
    }
    assert ready.status_code == 200
    assert ready.json()["provider"] == "mineru"
    assert ready.json()["api_profile"] == "mineru-api-v3"
    assert ready.json()["version"] == "3.4.4"
    assert ready.json()["protocol"] == "fastgpt-pdf-v2"
    assert ready.json()["provider_protocol"] == "2"


@pytest.mark.parametrize(
    "error",
    [
        ProviderUnavailable(),
        ProviderTimeout(),
        ProviderProcessingError("failed", 503),
        ProviderProtocolError("bad protocol"),
    ],
)
def test_provider_health_failures_are_not_ready(error: Exception) -> None:
    client, _ = client_for(FakeProvider(health_error=error))
    with client:
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json()["status"] == "not_ready"


def test_wrong_health_version_is_not_ready() -> None:
    client, _ = client_for(
        FakeProvider(health=ProviderHealth("healthy", "3.4.3", "2", 200))
    )
    with client:
        response = client.get("/health/ready")
    assert response.status_code == 503


@pytest.mark.parametrize(
    ("content", "content_type", "expected_status", "code"),
    [
        (b"", "application/pdf", 400, "EMPTY_FILE"),
        (b"plain text", "text/plain", 415, "UNSUPPORTED_MEDIA_TYPE"),
        (b"plain text", "application/pdf", 415, "INVALID_PDF_TYPE"),
        (b"%PDF-broken", "application/pdf", 400, "INVALID_PDF"),
    ],
)
def test_upload_validation(
    content: bytes,
    content_type: str,
    expected_status: int,
    code: str,
) -> None:
    client, _ = client_for()
    with client:
        response = upload(client, content, content_type=content_type)
    assert response.status_code == expected_status
    assert response.json()["error"] == code


def test_encrypted_pdf_and_page_limit() -> None:
    client, _ = client_for(max_pages=1)
    with client:
        encrypted = upload(client, build_pdf(encrypted=True))
        too_many = upload(client, build_pdf(2))
    assert encrypted.status_code == 400
    assert encrypted.json()["error"] == "ENCRYPTED_PDF"
    assert too_many.status_code == 413
    assert too_many.json()["error"] == "PAGE_LIMIT_EXCEEDED"


def test_file_size_limit() -> None:
    client, _ = client_for(max_file_bytes=10)
    with client:
        response = upload(client)
    assert response.status_code == 413
    assert response.json()["error"] == "FILE_TOO_LARGE"


def test_multipart_field_name_and_extra_fields_are_rejected() -> None:
    client, _ = client_for()
    with client:
        wrong = client.post(
            "/v2/parse/file",
            files={"document": ("sample.pdf", build_pdf(), "application/pdf")},
            headers={"Authorization": "Bearer secret"},
        )
        extra = client.post(
            "/v2/parse/file",
            files={"file": ("sample.pdf", build_pdf(), "application/pdf")},
            data={"option": "not-allowed"},
            headers={"Authorization": "Bearer secret"},
        )
    assert wrong.status_code == 422
    assert wrong.json()["error"] == "INVALID_REQUEST"
    assert extra.status_code == 422
    assert extra.json()["error"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (ProviderTimeout(), 504, "CORE_TIMEOUT"),
        (ProviderUnavailable(), 503, "CORE_UNAVAILABLE"),
        (ProviderProcessingError("failed", 500), 502, "CORE_PARSE_FAILED"),
        (ProviderProtocolError("bad"), 502, "CORE_PARSE_FAILED"),
    ],
)
def test_provider_parse_errors_are_mapped(
    error: Exception,
    status: int,
    code: str,
) -> None:
    client, _ = client_for(FakeProvider(parse_error=error))
    with client:
        response = upload(client)
    assert response.status_code == status
    assert response.json()["error"] == code


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (QueueFullError(), "PARSER_BUSY"),
        (QueueTimeoutError(), "QUEUE_TIMEOUT"),
    ],
)
def test_queue_errors_include_retry_after(error: Exception, code: str) -> None:
    client, _ = client_for()
    client.app.state.request_gate = FailingGate(error)
    with client:
        response = upload(client)
    assert response.status_code == 503
    assert response.json()["error"] == code
    assert response.headers["Retry-After"] == "5"


def test_unresolved_images_are_rejected() -> None:
    provider = FakeProvider(
        result=ProviderResult("![missing](images/no.png)", {}, 200)
    )
    client, _ = client_for(provider)
    with client:
        response = upload(client)
    assert response.status_code == 502
    assert response.json()["error"] == "IMAGE_CONVERSION_FAILED"


def test_unexpected_error_is_sanitized() -> None:
    client, _ = client_for(FakeProvider(parse_error=RuntimeError("private detail")))
    with client:
        response = upload(client)
    assert response.status_code == 500
    assert response.json()["error"] == "INTERNAL_ERROR"
    assert "private detail" not in response.text


def test_valid_request_id_is_preserved_and_invalid_one_is_replaced() -> None:
    client, _ = client_for()
    with client:
        valid = client.get("/health/live", headers={"X-Request-ID": "request-123"})
        invalid = client.get("/health/live", headers={"X-Request-ID": "bad value"})
    assert valid.headers["X-Request-ID"] == "request-123"
    assert invalid.headers["X-Request-ID"] != "bad value"
