import httpx
import pytest
from conftest import build_pdf
from fastapi.testclient import TestClient

from fastgpt_ocr_adapter.app import create_app
from fastgpt_ocr_adapter.config import Settings
from fastgpt_ocr_adapter.errors import ProviderConfigurationError


@pytest.mark.parametrize(
    ("legacy", "modern", "expected_version", "profile"),
    [
        ("3.4.4", None, "auto", "mineru-api-v3"),
        (None, "4.2.3", "auto", "mineru-tasks-v1"),
        (None, "4.2.3", "4.2.3", "mineru-tasks-v1"),
        (None, "4.0.12", "auto", None),
        (None, "4.2.3", "3.4.4", None),
        ("3.4.4", "4.2.3", "auto", None),
        (None, None, "auto", None),
    ],
)
def test_startup_detection(monkeypatch, legacy, modern, expected_version, profile):
    seen = []

    def handler(request):
        assert request.url.host == "mineru.test"
        assert request.method == "GET"
        seen.append(request.url.path)
        if request.url.path == "/service/health":
            assert "authorization" not in request.headers
            if legacy:
                return httpx.Response(
                    200, json={"status": "healthy", "version": legacy, "protocol_version": 2}
                )
        elif request.url.path == "/service/v1/health":
            assert request.headers["authorization"] == "Bearer upstream-test"
            if modern:
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "version": modern,
                        "features": {"sources": ["upload"], "task_output_formats": ["default"]},
                    },
                )
        else:
            raise AssertionError(request.url.path)
        return httpx.Response(404)

    client_type = httpx.AsyncClient

    def mock_client(**kwargs):
        return client_type(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mock_client)
    settings = Settings(
        api_profile="auto",
        provider_version=expected_version,
        mineru_base_url="http://mineru.test/service",
        mineru_auth_token="upstream-test",
        require_auth=False,
    )
    with TestClient(create_app(settings)) as client:
        assert set(seen) == {"/service/health", "/service/v1/health"}
        assert client.get("/health/live").status_code == 200
        ready = client.get("/health/ready")
        if profile:
            assert ready.status_code == 200
            assert ready.json()["api_profile"] == profile
            assert ready.json()["version"] == (modern or legacy)
        else:
            assert ready.status_code == 503
            assert ready.json()["message"]
            before = list(seen)
            result = client.post(
                "/v2/parse/file", files={"file": ("x.pdf", build_pdf(), "application/pdf")}
            )
            assert result.status_code == 503
            assert result.json()["error"] == "CORE_UNAVAILABLE"
            assert seen == before


def test_auto_env_defaults_to_discovery(monkeypatch):
    monkeypatch.setenv("FASTGPT_OCR_API_PROFILE", "auto")
    monkeypatch.delenv("FASTGPT_OCR_PROVIDER_VERSION", raising=False)
    assert Settings.from_env().provider_version == "auto"


def test_auto_does_not_infer_marker_versions():
    with pytest.raises(ProviderConfigurationError, match="only supported for MinerU"):
        create_app(Settings(provider="marker", api_profile="auto"))
