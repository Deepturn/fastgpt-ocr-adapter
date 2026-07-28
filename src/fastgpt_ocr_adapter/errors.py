from __future__ import annotations


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers or {}


class ProviderConfigurationError(ValueError):
    """The selected provider, profile, or version is not supported."""


class ProviderUnavailable(Exception):
    """The selected parser service cannot be reached."""


class ProviderTimeout(Exception):
    """The selected parser service exceeded the configured timeout."""


class ProviderProtocolError(Exception):
    """The selected parser service returned an unexpected protocol payload."""


class ProviderProcessingError(Exception):
    """The selected parser service rejected or failed a parsing request."""

    def __init__(self, message: str = "", status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
