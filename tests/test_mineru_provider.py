from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from fastgpt_ocr_adapter.config import Settings
from fastgpt_ocr_adapter.errors import (
    ProviderProcessingError,
    ProviderProtocolError,
    ProviderUnavailable,
)
from fastgpt_ocr_adapter.providers.mineru import MineruV3Provider


def provider_with_handler(handler) -> MineruV3Provider:
    provider = MineruV3Provider(Settings())
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


@pytest.mark.asyncio
async def test_mineru_request_uses_official_fixed_fields(tmp_path: Path) -> None:
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = (await request.aread()).decode("latin1")
        return httpx.Response(
            200,
            json={
                "version": "3.4.4",
                "results": {"file": {"md_content": "# parsed", "images": {}}},
            },
        )

    provider = provider_with_handler(handler)
    path = tmp_path / "test.pdf"
    path.write_bytes(b"%PDF-test")
    try:
        result = await provider.parse(path)
    finally:
        await provider.close()
    assert captured["path"] == "/file_parse"
    for name in (
        "files",
        "backend",
        "lang_list",
        "parse_method",
        "formula_enable",
        "table_enable",
        "return_md",
        "return_images",
        "response_format_zip",
    ):
        assert f'name="{name}"' in captured["body"]
    assert "pipeline" in captured["body"]
    assert result.markdown == "# parsed"


@pytest.mark.asyncio
async def test_mineru_health_validates_version_and_protocol() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(
            200,
            json={"status": "healthy", "version": "3.4.4", "protocol_version": 2},
        )

    provider = provider_with_handler(handler)
    try:
        health = await provider.health()
    finally:
        await provider.close()
    assert health.version == "3.4.4"
    assert health.protocol_version == "2"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        b"not-json",
        ["not-an-object"],
        {"version": "3.4.3", "results": {"file": {"md_content": "x"}}},
        {"version": "3.4.4", "results": {}},
        {"version": "3.4.4", "results": {"file": {}}},
        {
            "version": "3.4.4",
            "results": {"file": {"md_content": "x", "images": []}},
        },
    ],
)
async def test_mineru_rejects_invalid_parse_payload(
    tmp_path: Path,
    payload: object,
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        if isinstance(payload, bytes):
            return httpx.Response(200, content=payload)
        return httpx.Response(200, json=payload)

    provider = provider_with_handler(handler)
    path = tmp_path / "test.pdf"
    path.write_bytes(b"%PDF-test")
    try:
        with pytest.raises(ProviderProtocolError):
            await provider.parse(path)
    finally:
        await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        b"bad-json",
        [],
        {"status": "unhealthy", "version": "3.4.4", "protocol_version": 2},
        {"status": "healthy", "version": "3.4.3", "protocol_version": 2},
        {"status": "healthy", "version": "3.4.4"},
        {"status": "healthy", "version": "3.4.4", "protocol_version": True},
    ],
)
async def test_mineru_rejects_invalid_health(payload: object) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        del request
        if isinstance(payload, bytes):
            return httpx.Response(200, content=payload)
        return httpx.Response(200, json=payload)

    provider = provider_with_handler(handler)
    try:
        with pytest.raises(ProviderProtocolError):
            await provider.health()
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_mineru_http_and_connection_errors(tmp_path: Path) -> None:
    async def http_error(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(500)

    provider = provider_with_handler(http_error)
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

    provider = provider_with_handler(connection_error)
    try:
        with pytest.raises(ProviderUnavailable):
            await provider.parse(path)
        with pytest.raises(ProviderUnavailable):
            await provider.health()
    finally:
        await provider.close()
