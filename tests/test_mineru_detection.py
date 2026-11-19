import asyncio
import importlib

import httpx
import pytest
from conftest import build_pdf
from fastapi.testclient import TestClient

from fastgpt_ocr_adapter.app import create_app
from fastgpt_ocr_adapter.config import Settings
from fastgpt_ocr_adapter.errors import ProviderConfigurationError
from fastgpt_ocr_adapter.providers.base import ProviderHealth, ProviderResult
from fastgpt_ocr_adapter.providers.detect import detect_mineru

app_module = importlib.import_module("fastgpt_ocr_adapter.app")


class RecoveringDriver:
    name = "mineru"
    api_profile = "mineru-tasks-v1"
    version = "4.2.3"

    def __init__(self):
        self.closed = 0
        self.healthy = True
        self.parses = 0

    async def health(self):
        return ProviderHealth(
            "healthy" if self.healthy else "unhealthy", self.version, "1", 200
        )

    async def parse(self, path):
        assert path.read_bytes().startswith(b"%PDF-")
        self.parses += 1
        return ProviderResult("recovered markdown", {}, 200)

    async def close(self):
        self.closed += 1


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


async def test_auto_retries_with_capped_backoff_and_recovers(monkeypatch):
    driver = RecoveringDriver()
    attempts = 0
    delays = []
    recovered = asyncio.Event()

    async def detect(settings):
        nonlocal attempts
        attempts += 1
        if attempts <= 8:
            raise ProviderConfigurationError("upstream warming up")
        recovered.set()
        return driver

    async def wait(delay):
        delays.append(delay)
        await asyncio.sleep(0)

    monkeypatch.setattr(app_module, "detect_mineru", detect)
    monkeypatch.setattr(app_module, "_wait_mineru_retry", wait)
    app = create_app(Settings(api_profile="auto", provider_version="auto", require_auth=False))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://adapter"
        ) as client:
            await asyncio.wait_for(recovered.wait(), 2)
            ready = await client.get("/health/ready")
            assert ready.status_code == 200
            assert ready.json()["api_profile"] == driver.api_profile
            assert ready.json()["version"] == "4.2.3"
            result = await client.post(
                "/v2/parse/file", files={"file": ("x.pdf", build_pdf(), "application/pdf")}
            )
            assert result.status_code == 200
            assert result.json()["markdown"] == "recovered markdown"
            assert result.json()["pages"] == 1
            assert driver.parses == 1
    assert delays == [1, 2, 4, 8, 16, 30, 30, 30]
    assert driver.closed == 1
    assert app.state.provider is None


async def test_requests_do_not_start_parallel_detection_and_driver_is_frozen(monkeypatch):
    driver = RecoveringDriver()
    attempts = 0
    active = 0
    max_active = 0
    entered = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()

    async def detect(settings):
        nonlocal attempts, active, max_active
        attempts += 1
        if attempts == 1:
            raise ProviderConfigurationError("not ready")
        active += 1
        max_active = max(max_active, active)
        entered.set()
        try:
            await release.wait()
            return driver
        finally:
            active -= 1
            completed.set()

    async def wait(delay):
        await asyncio.sleep(0)

    monkeypatch.setattr(app_module, "detect_mineru", detect)
    monkeypatch.setattr(app_module, "_wait_mineru_retry", wait)
    app = create_app(Settings(api_profile="auto", provider_version="auto", require_auth=False))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app), base_url="http://adapter"
        ) as client:
            await asyncio.wait_for(entered.wait(), 2)
            responses = await asyncio.gather(
                *[client.get("/health/ready") for _ in range(12)],
                *[client.post("/v2/parse/file") for _ in range(12)],
            )
            assert all(response.status_code == 503 for response in responses)
            assert attempts == 2
            assert max_active == 1
            assert (await client.get("/health/live")).status_code == 200
            release.set()
            await asyncio.wait_for(completed.wait(), 2)
            assert (await client.get("/health/ready")).status_code == 200
            driver.healthy = False
            responses = await asyncio.gather(
                *[client.get("/health/ready") for _ in range(12)]
            )
            assert all(response.status_code == 503 for response in responses)
            assert attempts == 2  # A later outage must not select another protocol.
            assert app.state.provider is driver
            driver.healthy = True
            assert (await client.get("/health/ready")).status_code == 200
    assert driver.closed == 1


@pytest.mark.parametrize("pending_probe", [False, True])
async def test_shutdown_cancels_auto_retry_without_leaking_task(monkeypatch, pending_probe):
    attempts = 0
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def detect(settings):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ProviderConfigurationError("not ready")
        await blocked()
        raise AssertionError("cancelled probe continued")

    async def wait(delay):
        if pending_probe:
            return
        await blocked()

    monkeypatch.setattr(app_module, "detect_mineru", detect)
    monkeypatch.setattr(app_module, "_wait_mineru_retry", wait)
    app = create_app(Settings(api_profile="auto", provider_version="auto", require_auth=False))
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(entered.wait(), 2)
    assert cancelled.is_set()
    assert attempts == (2 if pending_probe else 1)
    assert app.state.provider is None
    assert not any(task.get_name() == "mineru-detection" for task in asyncio.all_tasks())


async def test_cancelled_detection_closes_already_validated_candidate(monkeypatch):
    detection_module = importlib.import_module("fastgpt_ocr_adapter.providers.detect")
    driver = RecoveringDriver()
    candidate_validated = asyncio.Event()
    sibling_waiting = asyncio.Event()

    async def health():
        candidate_validated.set()
        return ProviderHealth("healthy", "4.2.3", "1", 200)

    async def handler(request):
        if request.url.path == "/health":
            return httpx.Response(200, json={"version": "4.2.3"})
        await candidate_validated.wait()
        sibling_waiting.set()
        await asyncio.Event().wait()
        raise AssertionError("cancelled sibling continued")

    client_type = httpx.AsyncClient
    monkeypatch.setattr(driver, "health", health)
    monkeypatch.setattr(detection_module, "create_provider", lambda settings: driver)
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
    )
    task = asyncio.create_task(detect_mineru(Settings(
        api_profile="auto", provider_version="auto", mineru_base_url="http://mineru.test"
    )))
    await asyncio.wait_for(sibling_waiting.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert driver.closed == 1
