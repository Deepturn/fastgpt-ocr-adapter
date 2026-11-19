from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import quote

import httpx

from ..config import Settings
from ..errors import (
    ProviderProcessingError,
    ProviderProtocolError,
    ProviderTimeout,
    ProviderUnavailable,
)
from .base import ProviderHealth, ProviderResult
from .mineru import MineruV3Provider
from .mineru_archive import decode_mineru_archive

_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_POLL_SECONDS = 1.0


async def _file_chunks(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as handle:
        while chunk := handle.read(256 * 1024):
            yield chunk


class MineruTasksProvider:
    name = "mineru"
    api_profile = "mineru-tasks-v1"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.version = settings.provider_version
        self.base = httpx.URL(settings.mineru_base_url)
        self.client = httpx.AsyncClient(
            headers=(
                {"Authorization": f"Bearer {settings.mineru_auth_token}"}
                if settings.mineru_auth_token
                else {}
            ),
            timeout=httpx.Timeout(settings.timeout_seconds, connect=10.0),
            follow_redirects=False,
        )

    async def close(self) -> None:
        await self.client.aclose()

    def _transfer_url(self, value: object) -> httpx.URL:
        if not isinstance(value, str) or not value:
            raise ProviderProtocolError("MinerU returned no transfer URL")
        try:
            url = self.base.join(value)
        except httpx.InvalidURL as exc:
            raise ProviderProtocolError("MinerU returned an invalid transfer URL") from exc
        if (
            (url.scheme, url.host, url.port) != (self.base.scheme, self.base.host, self.base.port)
            or url.userinfo
            or url.fragment
        ):
            raise ProviderProtocolError("MinerU transfer URL must use the configured API origin")
        return url

    @staticmethod
    def _check(response: httpx.Response, expected: int | None = None) -> None:
        if not response.is_success or (expected is not None and response.status_code != expected):
            raise ProviderProcessingError(
                f"MinerU Tasks returned HTTP {response.status_code}",
                status_code=response.status_code,
            )

    @staticmethod
    def _file(payload: dict) -> dict:
        files = payload.get("files")
        if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
            raise ProviderProtocolError("MinerU Tasks returned an invalid file list")
        return files[0]

    async def health(self) -> ProviderHealth:
        try:
            response = await self.client.get(f"{self.base}/v1/health", timeout=5.0)
        except httpx.TimeoutException as exc:
            raise ProviderTimeout from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailable from exc
        self._check(response, 200)
        payload = MineruV3Provider._json_object(response, "MinerU Tasks health")
        features = payload.get("features")
        if (
            payload.get("status") != "ok"
            or payload.get("version") != self.settings.provider_version
            or not isinstance(features, dict)
            or not isinstance(features.get("sources"), list)
            or "upload" not in features["sources"]
            or not isinstance(features.get("task_output_formats"), list)
            or "default" not in features["task_output_formats"]
        ):
            raise ProviderProtocolError("MinerU Tasks health version or capabilities mismatch")
        return ProviderHealth(
            "healthy", self.settings.provider_version, "tasks-v1", response.status_code
        )

    async def parse(self, path: Path) -> ProviderResult:
        task_url: str | None = None
        pending = False
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                size = path.stat().st_size
                response = await self.client.post(
                    f"{self.base}/v1/tasks",
                    json={
                        "files": [{"file_name": "file.pdf", "bytes": size}],
                        "ocr_mode": "auto",
                        "output_formats": ["default"],
                    },
                )
                self._check(response, 202)
                receipt = MineruV3Provider._json_object(response, "MinerU Tasks creation")
                task_id = receipt.get("task_id")
                if not isinstance(task_id, str) or not task_id or task_id in {".", ".."}:
                    raise ProviderProtocolError("MinerU Tasks returned an invalid task ID")
                task_url = f"{self.base}/v1/tasks/{quote(task_id, safe='')}"
                pending = True
                file = self._file(receipt)
                file_id = file.get("file_id")
                if not isinstance(file_id, str) or not file_id:
                    raise ProviderProtocolError("MinerU Tasks returned an invalid file ID")
                upload = file.get("upload")
                if upload is not None:
                    if not isinstance(upload, dict) or upload.get("headers") not in (
                        {},
                        {"Content-Type": "application/octet-stream"},
                    ):
                        raise ProviderProtocolError("Expected a local MinerU upload target")
                    response = await self.client.put(
                        self._transfer_url(upload.get("url")),
                        headers={
                            "Content-Length": str(size),
                            "Content-Type": "application/octet-stream",
                        },
                        content=_file_chunks(path),
                    )
                    self._check(response)
                while True:
                    response = await self.client.get(task_url)
                    self._check(response, 200)
                    detail = MineruV3Provider._json_object(response, "MinerU Tasks status")
                    file = self._file(detail)
                    if detail.get("task_id") != task_id or file.get("file_id") != file_id:
                        raise ProviderProtocolError("MinerU Tasks returned mismatched identifiers")
                    state = file.get("status")
                    if state == "completed":
                        pending = False
                        metadata = file.get("parse")
                        if (
                            not isinstance(metadata, dict)
                            or metadata.get("parser_version") != self.settings.provider_version
                        ):
                            raise ProviderProtocolError("MinerU Tasks parse version mismatch")
                        return await self._download(self._transfer_url(file.get("result_url")))
                    if state in ("failed", "canceled"):
                        pending = False
                        raise ProviderProcessingError(
                            "MinerU Tasks did not complete", status_code=200
                        )
                    if state not in ("waiting-file", "pending", "running"):
                        raise ProviderProtocolError("MinerU Tasks returned an unknown file status")
                    await asyncio.sleep(_POLL_SECONDS)
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ProviderTimeout from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailable from exc
        finally:
            if task_url is not None and pending:
                try:
                    async with asyncio.timeout(1):
                        await self.client.post(f"{task_url}/cancel")
                except (TimeoutError, httpx.RequestError):
                    pass

    async def _download(self, url: httpx.URL) -> ProviderResult:
        content = bytearray()
        async with self.client.stream("GET", url) as response:
            self._check(response, 200)
            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                if len(content) + len(chunk) > _MAX_ARCHIVE_BYTES:
                    raise ProviderProtocolError("MinerU Tasks result ZIP exceeds the size limit")
                content.extend(chunk)
        return decode_mineru_archive(bytes(content), response.status_code)
