from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import httpx
import pytest

from fastgpt_ocr_adapter.config import Settings
from fastgpt_ocr_adapter.errors import ProviderProtocolError, ProviderTimeout
from fastgpt_ocr_adapter.images import rewrite_images
from fastgpt_ocr_adapter.providers.mineru_tasks import MineruTasksProvider


def settings(provider_version="4.2.3", **kwargs):
    return Settings(
        api_profile="mineru-tasks-v1",
        provider_version=provider_version,
        mineru_base_url="http://ocr.test/proxy",
        mineru_auth_token="upstream-test",
        **kwargs,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "version", [*(f"4.1.{patch}" for patch in range(8)), *(f"4.2.{patch}" for patch in range(4))]
)
async def test_tasks_full_wire_contract(tmp_path: Path, monkeypatch, version: str) -> None:
    monkeypatch.setattr("fastgpt_ocr_adapter.providers.mineru_tasks._POLL_SECONDS", 0)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        zipped.writestr("markdown.md", "# parsed\n![](images/sample.jpg)")
        zipped.writestr("images/sample.jpg", b"\xff\xd8\xfftest")
        zipped.writestr("middle_json.json", "{}")
        zipped.writestr("structured_content.json", "[]")
    pdf = tmp_path / "input.pdf"
    pdf.write_bytes(b"%PDF-test")
    calls = []

    async def handler(request):
        path = request.url.path
        calls.append((request.method, path))
        assert request.headers["authorization"] == "Bearer upstream-test"
        if path.endswith("/health"):
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "version": version,
                    "features": {"sources": ["upload", "url"], "task_output_formats": ["default"]},
                },
            )
        if request.method == "POST":
            assert path == "/proxy/v1/tasks"
            assert json.loads(await request.aread()) == {
                "files": [{"file_name": "file.pdf", "bytes": 9}],
                "ocr_mode": "auto",
                "output_formats": ["default"],
            }
            return httpx.Response(
                202,
                json={
                    "task_id": "task1",
                    "files": [
                        {
                            "file_id": "file1",
                            "upload": {
                                "url": "http://ocr.test/proxy/v1/tasks/task1/uploads/file1",
                                "headers": {"Content-Type": "application/octet-stream"},
                                "expires_at": 1800003600,
                            },
                        }
                    ],
                },
            )
        if request.method == "PUT":
            assert await request.aread() == b"%PDF-test"
            assert request.headers["content-length"] == "9"
            assert request.headers["content-type"] == "application/octet-stream"
            return httpx.Response(200)
        if path.endswith("/task1"):
            file = {"file_id": "file1", "status": "running"}
            if calls.count(("GET", path)) > 1:
                file.update(
                    status="completed",
                    parse={"parser_version": version},
                    result_url="/proxy/v1/files/file1/content",
                )
            return httpx.Response(200, json={"task_id": "task1", "files": [file]})
        assert path == "/proxy/v1/files/file1/content"
        return httpx.Response(200, content=archive.getvalue())

    provider = MineruTasksProvider(settings(version))
    await provider.close()
    provider.client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers=provider.client.headers
    )
    try:
        assert (await provider.health()).protocol_version == "tasks-v1"
        result = await provider.parse(pdf)
    finally:
        await provider.close()
    assert rewrite_images(result.markdown, result.images).startswith(
        "# parsed\n![](data:image/jpeg;base64,"
    )
    assert [method for method, _ in calls] == ["GET", "POST", "PUT", "GET", "GET", "GET"]


@pytest.mark.asyncio
@pytest.mark.parametrize("foreign_url", ["https://other.test/upload", "//other.test/upload"])
async def test_tasks_rejects_foreign_transfer(tmp_path: Path, foreign_url: str) -> None:
    pdf = tmp_path / "input.pdf"
    pdf.write_bytes(b"%PDF-test")

    def handler(request):
        assert request.url.host == "ocr.test"
        assert request.method == "POST"
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200)
        return httpx.Response(
            202,
            json={
                "task_id": "task1",
                "files": [{"file_id": "file1", "upload": {"url": foreign_url, "headers": {}}}],
            },
        )

    provider = MineruTasksProvider(settings())
    await provider.close()
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderProtocolError):
            await provider.parse(pdf)
    finally:
        await provider.close()


@pytest.mark.asyncio
async def test_tasks_timeout_cancels_pending_task(tmp_path: Path) -> None:
    pdf = tmp_path / "input.pdf"
    pdf.write_bytes(b"%PDF-test")
    canceled = False

    def handler(request):
        nonlocal canceled
        if request.url.path.endswith("/cancel"):
            canceled = True
            return httpx.Response(200)
        if request.method == "POST":
            return httpx.Response(202, json={"task_id": "task1", "files": [{"file_id": "file1"}]})
        return httpx.Response(
            200, json={"task_id": "task1", "files": [{"file_id": "file1", "status": "running"}]}
        )

    provider = MineruTasksProvider(settings(timeout_seconds=0.05))
    await provider.close()
    provider.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ProviderTimeout):
            await provider.parse(pdf)
    finally:
        await provider.close()
    assert canceled


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload", [{"status": "ok", "version": "4.2.3"}, {"status": "ok", "version": "4.2.2"}]
)
async def test_tasks_health_rejects_wrong_protocol(payload) -> None:
    provider = MineruTasksProvider(settings())
    await provider.close()
    provider.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    )
    try:
        with pytest.raises(ProviderProtocolError):
            await provider.health()
    finally:
        await provider.close()
