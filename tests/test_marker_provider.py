from __future__ import annotations

import base64
from pathlib import Path

import httpx
import pytest

from fastgpt_ocr_adapter.config import Settings
from fastgpt_ocr_adapter.errors import (
    ProviderProcessingError,
    ProviderProtocolError,
    ProviderUnavailable,
)
from fastgpt_ocr_adapter.providers.marker import MarkerProvider

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\npayload").decode()


def openapi(fields: set[str], *, inline: bool = False) -> dict:
    schema = {
        "type": "object",
        "properties": {name: {"type": "string"} for name in fields},
    }
    request_schema = schema if inline else {"$ref": "#/components/schemas/MarkerUpload"}
    document = {
        "paths": {
            "/marker/upload": {
                "post": {
                    "requestBody": {
                        "content": {
                            "multipart/form-data": {
                                "schema": request_schema,
                            }
                        }
                    }
                }
            }
        }
    }
    if not inline:
        document["components"] = {"schemas": {"MarkerUpload": schema}}
    return document


def marker_provider(
    handler,
    *,
    profile: str = "marker-server-v1",
    version: str = "1.10.2",
    token: str = "",
) -> MarkerProvider:
    settings = Settings(
        provider="marker",
        api_profile=profile,
        provider_version=version,
        marker_base_url="http://marker:8000",
        marker_auth_token=token,
    )
    provider = MarkerProvider(
        settings,
        api_profile=profile,
        supports_mode=profile == "marker-server-v2",
    )
    provider.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers=provider._headers(),
    )
    return provider


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "version", "has_mode"),
    [
        ("marker-server-v1", "1.10.2", False),
        ("marker-server-v2", "2.0.0", True),
    ],
)
async def test_marker_profiles_send_version_specific_fields(
    tmp_path: Path,
    profile: str,
    version: str,
    has_mode: bool,
) -> None:
    body = ""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal body
        assert request.url.path == "/marker/upload"
        body = (await request.aread()).decode("latin1")
        return httpx.Response(
            200,
            json={
                "success": True,
                "format": "markdown",
                "output": "![img](image.png)",
                "images": {"image.png": PNG},
                "metadata": {},
            },
        )

    provider = marker_provider(handler, profile=profile, version=version)
    path = tmp_path / "test.pdf"
    path.write_bytes(b"%PDF-test")
    try:
        result = await provider.parse(path)
    finally:
        await provider.close()
    assert 'name="file"' in body
    assert 'name="force_ocr"' in body
    assert 'name="paginate_output"' in body
    assert 'name="output_format"' in body
    assert ('name="mode"' in body) is has_mode
    assert result.images["image.png"].startswith("data:image/png;base64,")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "version", "fields"),
    [
        (
            "marker-server-v1",
            "1.10.2",
            {"file", "force_ocr", "paginate_output", "output_format"},
        ),
        (
            "marker-server-v2",
            "2.0.0",
            {"file", "force_ocr", "paginate_output", "output_format", "mode"},
        ),
    ],
)
async def test_marker_health_validates_openapi_profile(
    profile: str,
    version: str,
    fields: set[str],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/openapi.json"
        return httpx.Response(200, json=openapi(fields))

    provider = marker_provider(handler, profile=profile, version=version)
    try:
        health = await provider.health()
    finally:
        await provider.close()
    assert health.status == "healthy"
    assert health.version == version
    assert health.protocol_version == profile


@pytest.mark.asyncio
async def test_marker_health_accepts_inline_schema_and_proxy_auth() -> None:
    fields = {"file", "force_ocr", "paginate_output", "output_format"}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer upstream-secret"
        return httpx.Response(200, json=openapi(fields, inline=True))

    provider = marker_provider(handler, token="upstream-secret")
    try:
        assert (await provider.health()).status == "healthy"
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        [],
        {"success": False, "error": "failed"},
        {"success": True, "format": "html", "output": "x", "images": {}},
        {"success": True, "format": "markdown", "output": 1, "images": {}},
        {"success": True, "format": "markdown", "output": "x", "images": []},
        {
            "success": True,
            "format": "markdown",
            "output": "x",
            "images": {"x": "bad-base64"},
        },
        {
            "success": True,
            "format": "markdown",
            "output": "x",
            "images": {"x": 1},
        },
    ],
)
async def test_marker_rejects_invalid_parse_payload(
    tmp_path: Path,
    payload: object,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        if isinstance(payload, bytes):
            return httpx.Response(200, content=payload)
        return httpx.Response(200, json=payload)

    provider = marker_provider(handler)
    path = tmp_path / "test.pdf"
    path.write_bytes(b"%PDF-test")
    try:
        expected = (
            ProviderProcessingError
            if isinstance(payload, dict) and payload.get("success") is False
            else ProviderProtocolError
        )
        with pytest.raises(expected):
            await provider.parse(path)
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("profile", "fields"),
    [
        (
            "marker-server-v1",
            {"file", "force_ocr", "paginate_output", "output_format", "mode"},
        ),
        (
            "marker-server-v2",
            {"file", "force_ocr", "paginate_output", "output_format"},
        ),
    ],
)
async def test_marker_rejects_profile_schema_mismatch(
    profile: str,
    fields: set[str],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, json=openapi(fields))

    provider = marker_provider(
        handler,
        profile=profile,
        version="1.10.2" if profile.endswith("v1") else "2.0.0",
    )
    try:
        with pytest.raises(ProviderProtocolError):
            await provider.health()
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        b"bad-json",
        [],
        {"paths": {}},
        {
            "paths": {
                "/marker/upload": {
                    "post": {
                        "requestBody": {
                            "content": {
                                "multipart/form-data": {"schema": {"type": "object"}}
                            }
                        }
                    }
                }
            }
        },
        openapi({"file", "force_ocr", "paginate_output", "output_format"})
        | {"components": {"schemas": {}}},
    ],
)
async def test_marker_rejects_invalid_openapi(payload: object) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        if isinstance(payload, bytes):
            return httpx.Response(200, content=payload)
        return httpx.Response(200, json=payload)

    provider = marker_provider(handler)
    try:
        with pytest.raises(ProviderProtocolError):
            await provider.health()
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_marker_http_and_connection_errors(tmp_path: Path) -> None:
    async def http_error(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(503)

    provider = marker_provider(http_error)
    path = tmp_path / "test.pdf"
    path.write_bytes(b"%PDF-test")
    try:
        with pytest.raises(ProviderProcessingError):
            await provider.parse(path)
        with pytest.raises(ProviderProcessingError):
            await provider.health()
    finally:
        await provider.close()

    async def connection_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    provider = marker_provider(connection_error)
    try:
        with pytest.raises(ProviderUnavailable):
            await provider.parse(path)
        with pytest.raises(ProviderUnavailable):
            await provider.health()
    finally:
        await provider.close()
