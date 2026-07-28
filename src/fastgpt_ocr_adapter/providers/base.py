from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ProviderResult:
    markdown: str
    images: dict[str, str]
    upstream_status: int


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    status: str
    version: str
    protocol_version: str
    upstream_status: int


class ParserProvider(Protocol):
    name: str
    api_profile: str
    version: str

    async def parse(self, path: Path) -> ProviderResult: ...

    async def health(self) -> ProviderHealth: ...

    async def close(self) -> None: ...
