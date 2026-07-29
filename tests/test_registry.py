from __future__ import annotations

from pathlib import Path

import pytest

from fastgpt_ocr_adapter.config import Settings
from fastgpt_ocr_adapter.errors import ProviderConfigurationError
from fastgpt_ocr_adapter.providers import create_provider, get_provider_spec, provider_specs

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("profile", "version"),
    [
        ("marker-server-v1", "1.8.0"),
        ("marker-server-v1", "1.10.2"),
        ("marker-server-v2", "2.0.0"),
    ],
)
def test_supported_marker_profiles(profile: str, version: str) -> None:
    spec = get_provider_spec(
        Settings(provider="marker", api_profile=profile, provider_version=version)
    )
    assert spec.name == "marker"
    assert spec.api_profile == profile


def test_registry_lists_all_profiles() -> None:
    assert {(spec.name, spec.api_profile) for spec in provider_specs()} == {
        ("mineru", "mineru-api-v3"),
        ("marker", "marker-server-v1"),
        ("marker", "marker-server-v2"),
    }


@pytest.mark.parametrize(
    "document",
    [
        PROJECT_ROOT / "README.md",
        PROJECT_ROOT / "deploy" / "customer" / "README.md",
    ],
)
def test_registered_profiles_are_documented(document: Path) -> None:
    content = document.read_text(encoding="utf-8")
    for spec in provider_specs():
        table_prefix = (
            f"| `{spec.name}` | `{spec.api_profile}` | `{spec.supported_versions}` |"
        )
        assert table_prefix in content, (
            f"{document.relative_to(PROJECT_ROOT)} must document "
            f"{spec.name}/{spec.api_profile} ({spec.supported_versions})"
        )


@pytest.mark.parametrize(
    "settings",
    [
        Settings(provider="unknown"),
        Settings(provider="marker", api_profile="mineru-api-v3"),
        Settings(
            provider="marker",
            api_profile="marker-server-v1",
            provider_version="2.0.0",
        ),
        Settings(
            provider="marker",
            api_profile="marker-server-v2",
            provider_version="2.1.0",
        ),
        Settings(provider_version="not-a-version"),
    ],
)
def test_unknown_or_unsupported_configuration_fails(settings: Settings) -> None:
    with pytest.raises(ProviderConfigurationError):
        get_provider_spec(settings)


@pytest.mark.asyncio
async def test_factory_builds_mineru_provider() -> None:
    provider = create_provider(Settings())
    try:
        assert provider.name == "mineru"
        assert provider.api_profile == "mineru-api-v3"
        assert provider.version == "3.4.4"
    finally:
        await provider.close()
