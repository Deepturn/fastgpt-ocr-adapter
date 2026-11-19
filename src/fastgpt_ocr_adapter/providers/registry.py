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
from .mineru_tasks import MineruTasksProvider

ProviderFactory = Callable[[Settings], ParserProvider]


@dataclass(frozen=True, slots=True)
class ProviderSpec:
    name: str
    api_profile: str
    supported_versions: str
    factory: ProviderFactory
    exact_versions: tuple[str, ...] = ()

    @property
    def documented_versions(self) -> str:
        return ", ".join(f"`{version}`" for version in self.exact_versions) or (
            f"`{self.supported_versions}`"
        )


_SPECS = (
    ProviderSpec(
        name="mineru",
        api_profile="mineru-api-v3",
        supported_versions="",
        factory=MineruV3Provider,
        exact_versions=("3.4.4", "3.4.5"),
    ),
    ProviderSpec(
        name="mineru",
        api_profile="mineru-tasks-v1",
        supported_versions="",
        factory=MineruTasksProvider,
        exact_versions=(
            "4.1.0", "4.1.1", "4.1.2", "4.1.3", "4.1.4", "4.1.5", "4.1.6", "4.1.7",
            "4.2.0", "4.2.1", "4.2.2", "4.2.3",
        ),
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
        profiles = ", ".join(f"{item.name}/{item.api_profile}" for item in _SPECS)
        raise ProviderConfigurationError(
            f"Unknown provider/profile {key[0]}/{key[1]}; supported: {profiles}"
        )
    try:
        version = Version(settings.provider_version)
        supported = (
            settings.provider_version in spec.exact_versions
            if spec.exact_versions
            else version in SpecifierSet(spec.supported_versions)
        )
    except (InvalidVersion, InvalidSpecifier) as exc:
        raise ProviderConfigurationError(
            f"Invalid provider version {settings.provider_version!r}"
        ) from exc
    if not supported:
        raise ProviderConfigurationError(
            f"{spec.name}/{spec.api_profile} does not support "
            f"{settings.provider_version}; expected {spec.documented_versions.replace('`', '')}"
        )
    return spec


def create_provider(settings: Settings) -> ParserProvider:
    return get_provider_spec(settings).factory(settings)
