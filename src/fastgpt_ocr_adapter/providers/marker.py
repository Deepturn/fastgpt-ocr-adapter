from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from ..config import Settings
from ..errors import (
    ProviderProcessingError,
    ProviderProtocolError,
    ProviderTimeout,
    ProviderUnavailable,
)
from ..images import ImageRewriteError, image_data_uri
from .base import ProviderHealth, ProviderResult


class MarkerProvider:
    name = "marker"

    def __init__(self, settings: Settings, *, api_profile: str, supports_mode: bool) -> None:
        self.settings = settings
        self.api_profile = api_profile
        self.supports_mode = supports_mode
        self.version = settings.provider_version
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                settings.timeout_seconds,
                connect=10.0,
                write=60.0,
                pool=10.0,
            ),
            headers=self._headers(),
        )

    def _headers(self) -> dict[str, str]:
        if self.settings.marker_auth_token:
            return {"Authorization": f"Bearer {self.settings.marker_auth_token}"}
        return {}

    async def close(self) -> None:
        await self.client.aclose()

    async def parse(self, path: Path) -> ProviderResult:
        fields = {
            "force_ocr": str(self.settings.marker_force_ocr).lower(),
            "paginate_output": "false",
            "output_format": "markdown",
        }
        if self.supports_mode:
            fields["mode"] = self.settings.marker_mode
        try:
            with path.open("rb") as handle:
                response = await self.client.post(
                    f"{self.settings.marker_base_url}/marker/upload",
                    data=fields,
                    files={"file": ("file.pdf", handle, "application/pdf")},
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailable from exc
        if response.status_code >= 400:
            raise ProviderProcessingError(
                f"Marker returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
        payload = self._json_object(response, "Marker")
        if payload.get("success") is not True:
            raise ProviderProcessingError("Marker reported a conversion failure")
        if payload.get("format") != "markdown":
            raise ProviderProtocolError("Marker did not return markdown format")
        markdown = payload.get("output")
        raw_images = payload.get("images")
        if not isinstance(markdown, str) or not isinstance(raw_images, dict):
            raise ProviderProtocolError("Marker returned an invalid conversion payload")
        try:
            images = {
                key: image_data_uri(value)
                for key, value in raw_images.items()
                if isinstance(key, str)
            }
        except ImageRewriteError as exc:
            raise ProviderProtocolError("Marker returned an invalid image map") from exc
        if len(images) != len(raw_images):
            raise ProviderProtocolError("Marker returned an invalid image key")
        return ProviderResult(
            markdown=markdown,
            images=images,
            upstream_status=response.status_code,
        )

    async def health(self) -> ProviderHealth:
        try:
            response = await self.client.get(
                f"{self.settings.marker_base_url}/openapi.json"
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout from exc
        except httpx.RequestError as exc:
            raise ProviderUnavailable from exc
        if response.status_code >= 400:
            raise ProviderProcessingError(
                f"Marker OpenAPI returned HTTP {response.status_code}",
                status_code=response.status_code,
            )
        payload = self._json_object(response, "Marker OpenAPI")
        fields = self._multipart_fields(payload)
        expected = {"file", "force_ocr", "paginate_output", "output_format"}
        if self.supports_mode:
            expected.add("mode")
        if not expected.issubset(fields):
            missing = ", ".join(sorted(expected - fields))
            raise ProviderProtocolError(
                f"Marker OpenAPI does not match {self.api_profile}; missing {missing}"
            )
        if not self.supports_mode and "mode" in fields:
            raise ProviderProtocolError(
                "Marker OpenAPI exposes v2 fields while marker-server-v1 is configured"
            )
        return ProviderHealth(
            status="healthy",
            version=self.version,
            protocol_version=self.api_profile,
            upstream_status=response.status_code,
        )

    @classmethod
    def _multipart_fields(cls, document: dict[str, Any]) -> set[str]:
        try:
            operation = document["paths"]["/marker/upload"]["post"]
            schema = operation["requestBody"]["content"]["multipart/form-data"]["schema"]
        except (KeyError, TypeError) as exc:
            raise ProviderProtocolError(
                "Marker OpenAPI does not expose POST /marker/upload"
            ) from exc
        resolved = cls._resolve_schema(document, schema)
        properties = resolved.get("properties")
        if not isinstance(properties, dict):
            raise ProviderProtocolError(
                "Marker OpenAPI multipart schema has no properties"
            )
        return set(properties)

    @staticmethod
    def _resolve_schema(document: dict[str, Any], schema: Any) -> dict[str, Any]:
        if not isinstance(schema, dict):
            raise ProviderProtocolError("Marker OpenAPI contains an invalid schema")
        reference = schema.get("$ref")
        if reference is None:
            return schema
        if not isinstance(reference, str) or not reference.startswith("#/"):
            raise ProviderProtocolError("Marker OpenAPI contains an unsupported schema reference")
        current: Any = document
        try:
            for part in reference[2:].split("/"):
                current = current[part.replace("~1", "/").replace("~0", "~")]
        except (KeyError, TypeError) as exc:
            raise ProviderProtocolError(
                "Marker OpenAPI contains an unresolved schema reference"
            ) from exc
        if not isinstance(current, dict):
            raise ProviderProtocolError("Marker OpenAPI resolved to an invalid schema")
        return current

    @staticmethod
    def _json_object(response: httpx.Response, source: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderProtocolError(f"{source} returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderProtocolError(f"{source} returned non-object JSON")
        return payload
