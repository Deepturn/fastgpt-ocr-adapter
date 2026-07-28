from __future__ import annotations

from pathlib import Path

import httpx

from ..config import Settings
from ..errors import (
    ProviderProcessingError,
    ProviderProtocolError,
    ProviderTimeout,
    ProviderUnavailable,
)
from .base import ProviderHealth, ProviderResult


class MineruV3Provider:
    name = "mineru"
    api_profile = "mineru-api-v3"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.version = settings.provider_version
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                settings.timeout_seconds,
                connect=10.0,
                write=60.0,
                pool=10.0,
            )
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def parse(self, path: Path) -> ProviderResult:
        fields = {
            "backend": "pipeline",
            "lang_list": "ch",
            "parse_method": "auto",
            "formula_enable": "true",
            "table_enable": "true",
            "return_md": "true",
            "return_images": "true",
            "response_format_zip": "false",
        }
        try:
            with path.open("rb") as handle:
                response = await self.client.post(
                    f"{self.settings.mineru_base_url}/file_parse",
                    data=fields,
                    files={"files": ("file.pdf", handle, "application/pdf")},
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailable from exc
        if response.status_code >= 400:
            raise ProviderProcessingError(
                f"MinerU returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
        payload = self._json_object(response, "MinerU")
        response_version = payload.get("version")
        if response_version is not None and response_version != self.version:
            raise ProviderProtocolError(
                f"MinerU returned version {response_version!r}; expected {self.version!r}"
            )
        results = payload.get("results")
        if not isinstance(results, dict) or len(results) != 1:
            raise ProviderProtocolError("MinerU returned an invalid result set")
        item = next(iter(results.values()))
        if not isinstance(item, dict) or not isinstance(item.get("md_content"), str):
            raise ProviderProtocolError("MinerU did not return markdown content")
        images = item.get("images", {})
        if not isinstance(images, dict):
            raise ProviderProtocolError("MinerU returned an invalid image map")
        return ProviderResult(
            markdown=item["md_content"],
            images=images,
            upstream_status=response.status_code,
        )

    async def health(self) -> ProviderHealth:
        try:
            response = await self.client.get(f"{self.settings.mineru_base_url}/health")
        except httpx.TimeoutException as exc:
            raise ProviderTimeout from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailable from exc
        if response.status_code >= 400:
            raise ProviderProcessingError(
                f"MinerU health returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
        payload = self._json_object(response, "MinerU health")
        status = payload.get("status")
        version = payload.get("version")
        protocol_version = payload.get("protocol_version")
        if status != "healthy":
            raise ProviderProtocolError("MinerU health did not report healthy")
        if not isinstance(version, str) or version != self.version:
            raise ProviderProtocolError(
                f"MinerU health version does not match expected {self.version}"
            )
        if not isinstance(protocol_version, (str, int)) or isinstance(
            protocol_version, bool
        ):
            raise ProviderProtocolError("MinerU health returned no protocol version")
        return ProviderHealth(
            status=status,
            version=version,
            protocol_version=str(protocol_version),
            upstream_status=response.status_code,
        )

    @staticmethod
    def _json_object(response: httpx.Response, source: str) -> dict:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderProtocolError(f"{source} returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderProtocolError(f"{source} returned non-object JSON")
        return payload
