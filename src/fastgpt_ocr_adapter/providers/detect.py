from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx

from ..config import Settings
from ..errors import (
    ProviderConfigurationError,
    ProviderProcessingError,
    ProviderProtocolError,
    ProviderTimeout,
    ProviderUnavailable,
)
from .base import ParserProvider
from .registry import create_provider


async def detect_mineru(settings: Settings) -> ParserProvider:
    """Resolve one registered MinerU contract without submitting any work."""
    candidates: list[ParserProvider] = []

    async def probe(
        client: httpx.AsyncClient, endpoint: str, profile: str
    ) -> ParserProvider | None:
        headers = {}
        if endpoint == "/v1/health" and settings.mineru_auth_token:
            headers["Authorization"] = f"Bearer {settings.mineru_auth_token}"
        try:
            async with asyncio.timeout(5):
                response = await client.get(
                    f"{settings.mineru_base_url}{endpoint}", headers=headers
                )
                if response.status_code == 404:
                    return None
                if response.status_code != 200:
                    raise ProviderProtocolError(f"MinerU {endpoint} did not report health")
                payload = response.json()
                version = payload.get("version") if isinstance(payload, dict) else None
                if not isinstance(version, str) or not version:
                    raise ProviderProtocolError(f"MinerU {endpoint} did not report a version")
                if settings.provider_version not in {"auto", version}:
                    raise ProviderProtocolError(
                        "MinerU reported a different version than configured"
                    )
                driver = create_provider(
                    replace(settings, api_profile=profile, provider_version=version)
                )
                try:
                    health = await driver.health()
                    if health.status != "healthy" or health.version != version:
                        raise ProviderProtocolError(
                            "MinerU health changed during startup detection"
                        )
                except BaseException:
                    await driver.close()
                    raise
                candidates.append(driver)
                return driver
        except (
            TimeoutError,
            httpx.HTTPError,
            ValueError,
            ProviderProcessingError,
            ProviderUnavailable,
            ProviderTimeout,
        ) as exc:
            raise ProviderProtocolError(f"MinerU {endpoint} failed startup validation") from exc

    try:
        async with httpx.AsyncClient(follow_redirects=False) as client:
            results = await asyncio.gather(
                probe(client, "/health", "mineru-api-v3"),
                probe(client, "/v1/health", "mineru-tasks-v1"),
                return_exceptions=True,
            )
    except BaseException:
        for driver in candidates:
            await driver.close()
        raise
    if len(candidates) == 1 and not any(isinstance(item, BaseException) for item in results):
        return candidates[0]
    for driver in candidates:
        await driver.close()
    if len(candidates) > 1:
        raise ProviderConfigurationError("Multiple MinerU profiles matched; select one explicitly")
    raise ProviderConfigurationError(
        "Could not identify a supported MinerU profile; check upstream health, version and API key"
    )
