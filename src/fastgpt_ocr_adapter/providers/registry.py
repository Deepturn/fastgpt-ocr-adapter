from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from ..config import Settings
from ..errors import ProviderConfigurationError
from .base import ParserProvider
from .marker import MarkerProvider
from .mineru import MineruV3Provider

ProviderFactory = Callable[[Settings], ParserProvider]


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    name: str
    api_profile: str
    supported_versions: str
    factory: ProviderFactory


_SPECS = (
    ProviderSpec(
        name="mineru",
        api_profile="mineru-api-v3",
        supported_versions="==3.4.4",
        factory=MineruV3Provider,
    ),
    ProviderSpec(
        name="marker",
        api_profile="marker-server-v1",
        supported_versions=">=1.8,<2.0",
        factory=lambda settings: MarkerProvider(
            settings, api_profile="marker-server-v1", supports_mode=False
        ),
    ),
    ProviderSpec(
        name="marker",
        api_profile="marker-server-v2",
        supported_versions="==2.0.0",
        factory=lambda settings: MarkerProvider(
            settings, api_profile="marker-server-v2", supports_mode=True
        ),
    ),
)
_REGISTRY = {(spec.name, spec.api_profile): spec for spec in _SPECS}


def provider_specs() -> tuple[ProviderSpec, ...]:
    return _SPECS


def get_provider_spec(settings: Settings) -> ProviderSpec:
    key = (settings.provider.strip().lower(), settings.api_profile.strip().lower())
    spec = _REGISTRY.get(key)
    if spec is None:
        supported = ", ".join(f"{item.name}/{item.api_profile}" for item in _SPECS)
        raise ProviderConfigurationError(
            f"Unknown provider/profile {key[0]}/{key[1]}; supported: {supported}"
        )
    try:
        version = Version(settings.provider_version)
        accepted = SpecifierSet(spec.supported_versions)
    except (InvalidVersion, InvalidSpecifier) as exc:
        raise ProviderConfigurationError(
            f"Invalid provider version {settings.provider_version!r}"
        ) from exc
    if version not in accepted:
        raise ProviderConfigurationError(
            f"{spec.name}/{spec.api_profile} does not support "
            f"{settings.provider_version}; expected {spec.supported_versions}"
        )
    return spec


def create_provider(settings: Settings) -> ParserProvider:
    return get_provider_spec(settings).factory(settings)
