from __future__ import annotations

import logging
import secrets
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pypdf import PdfReader

from . import __version__
from .config import Settings
from .errors import (
    ApiError,
    ProviderConfigurationError,
    ProviderProcessingError,
    ProviderProtocolError,
    ProviderTimeout,
    ProviderUnavailable,
)
from .gate import QueueFullError, QueueTimeoutError, RequestGate
from .images import ImageRewriteError, rewrite_images
from .providers import ParserProvider, ProviderResult, create_provider
from .providers.detect import detect_mineru

logger = logging.getLogger("fastgpt_ocr_adapter")
FASTGPT_PROTOCOL_VERSION = "fastgpt-pdf-v2"


def _request_id(request: Request) -> str:
    supplied = request.headers.get("X-Request-ID", "").strip()
    if supplied and len(supplied) <= 128 and all(
        char.isalnum() or char in "._:-" for char in supplied
    ):
        return supplied
    return uuid.uuid4().hex


def _auth_error(settings: Settings, request: Request) -> None:
    if not settings.require_auth:
        return
    if not settings.auth_token:
        raise ApiError(
            503,
            "AUTH_NOT_CONFIGURED",
            "Parser authentication is not configured",
        )
    authorization = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not authorization.startswith(prefix) or not secrets.compare_digest(
        authorization[len(prefix) :], settings.auth_token
    ):
        raise ApiError(401, "UNAUTHORIZED", "A valid Bearer token is required")


async def _save_upload(upload: UploadFile, settings: Settings) -> tuple[Path, int]:
    if upload.content_type not in {
        None,
        "",
        "application/pdf",
        "application/octet-stream",
    }:
        await upload.close()
        raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "Only PDF files are supported")

    handle = tempfile.NamedTemporaryFile(
        prefix="fastgpt-ocr-",
        suffix=".pdf",
        delete=False,
    )
    path = Path(handle.name)
    total = 0
    try:
        with handle:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_file_bytes:
                    raise ApiError(
                        413,
                        "FILE_TOO_LARGE",
                        "PDF exceeds the configured size limit",
                    )
                handle.write(chunk)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    if total == 0:
        path.unlink(missing_ok=True)
        raise ApiError(400, "EMPTY_FILE", "The uploaded PDF is empty")
    return path, total


def _inspect_pdf(path: Path, settings: Settings) -> int:
    with path.open("rb") as handle:
        if handle.read(5) != b"%PDF-":
            raise ApiError(415, "INVALID_PDF_TYPE", "The uploaded file is not a PDF")
    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            raise ApiError(400, "ENCRYPTED_PDF", "Encrypted PDFs are not supported")
        pages = len(reader.pages)
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(400, "INVALID_PDF", "The PDF could not be read") from exc
    if pages <= 0:
        raise ApiError(400, "EMPTY_PDF", "The PDF has no pages")
    if pages > settings.max_pages:
        raise ApiError(
            413,
            "PAGE_LIMIT_EXCEEDED",
            "PDF exceeds the configured page limit",
        )
    return pages


def create_app(
    settings: Settings | None = None,
    provider: ParserProvider | None = None,
) -> FastAPI:
    app_settings = settings or Settings.from_env()
    auto = app_settings.api_profile == "auto"
    if auto and app_settings.provider != "mineru":
        raise ProviderConfigurationError("Automatic profile detection is only supported for MinerU")
    selected_provider = provider if auto else provider or create_provider(app_settings)
    detection_error = "MinerU profile has not been resolved"
    request_gate = RequestGate(
        max_concurrent_requests=app_settings.max_concurrent_requests,
        max_queued_requests=app_settings.max_queued_requests,
        queue_timeout_seconds=app_settings.queue_timeout_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        nonlocal selected_provider, detection_error
        if auto and selected_provider is None:
            try:
                selected_provider = await detect_mineru(app_settings)
                app.state.provider = selected_provider
            except ProviderConfigurationError as exc:
                detection_error = str(exc)
        try:
            yield
        finally:
            if selected_provider is not None:
                await selected_provider.close()
                if auto and provider is None:
                    selected_provider = None
                    app.state.provider = None

    app = FastAPI(
        title="FastGPT OCR Adapter",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.provider = selected_provider
    app.state.request_gate = request_gate

    @app.middleware("http")
    async def request_logging(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = _request_id(request)
        started = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "request_failed request_id=%s method=%s path=%s",
                request.state.request_id,
                request.method,
                request.url.path,
            )
            raise
        response.headers["X-Request-ID"] = request.state.request_id
        logger.info(
            "request_complete request_id=%s method=%s path=%s status=%s "
            "size=%s pages=%s duration_ms=%s upstream_status=%s",
            request.state.request_id,
            request.method,
            request.url.path,
            response.status_code,
            getattr(request.state, "file_size", "-"),
            getattr(request.state, "pages", "-"),
            round((time.monotonic() - started) * 1000, 1),
            getattr(request.state, "upstream_status", "-"),
        )
        return response

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "message": exc.message,
                "error": exc.code,
            },
            headers={
                "X-Request-ID": getattr(request.state, "request_id", ""),
                **exc.headers,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del exc
        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "message": "The request must contain one PDF field named file",
                "error": "INVALID_REQUEST",
            },
            headers={"X-Request-ID": getattr(request.state, "request_id", "")},
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception(
            "unexpected_error request_id=%s error_type=%s",
            getattr(request.state, "request_id", "-"),
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": "The parser encountered an internal error",
                "error": "INTERNAL_ERROR",
            },
            headers={"X-Request-ID": getattr(request.state, "request_id", "")},
        )

    @app.get("/health/live")
    async def health_live() -> dict[str, str]:
        return {
            "status": "alive",
            "adapter_version": __version__,
            "provider": selected_provider.name if selected_provider else app_settings.provider,
            "api_profile": selected_provider.api_profile if selected_provider else "auto",
        }

    @app.get("/health/ready", response_model=None)
    @app.get("/health", response_model=None)
    async def health_ready(request: Request) -> dict[str, object] | JSONResponse:
        driver = selected_provider
        auth_configured = not app_settings.require_auth or bool(app_settings.auth_token)
        base = {
            "adapter_version": __version__,
            "provider": driver.name if driver else app_settings.provider,
            "api_profile": driver.api_profile if driver else "auto",
            "version": driver.version if driver and auto else app_settings.provider_version,
            "protocol": FASTGPT_PROTOCOL_VERSION,
            "auth_configured": auth_configured,
        }
        if not auth_configured:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", **base},
            )
        if driver is None:
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", **base, "message": detection_error},
            )
        try:
            provider_health = await driver.health()
            request.state.upstream_status = provider_health.upstream_status
        except (
            ProviderUnavailable,
            ProviderTimeout,
            ProviderProcessingError,
            ProviderProtocolError,
        ) as exc:
            request.state.upstream_status = getattr(exc, "status_code", None) or "-"
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", **base},
            )
        if (
            provider_health.status != "healthy"
            or provider_health.version != base["version"]
        ):
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", **base},
            )
        return {
            "status": "ready",
            **base,
            "provider_protocol": provider_health.protocol_version,
        }

    @app.post("/v2/parse/file")
    async def parse_file(
        request: Request,
        file: UploadFile = File(...),  # noqa: B008
    ) -> dict[str, object]:
        _auth_error(app_settings, request)
        driver = selected_provider
        if driver is None:
            raise ApiError(503, "CORE_UNAVAILABLE", "MinerU profile has not been resolved")
        form = await request.form()
        # Newer FastGPT releases include these optional parser-specific flags.
        # None of our provider profiles consumes them; never forward them upstream.
        optional_fields = {
            "keep_header_footer", "keep_appendix", "image_analysis", "chart_analysis"
        }
        invalid_flags = any(
            key != "file" and (key not in optional_fields or value not in ("true", "false"))
            for key, value in form.multi_items()
        )
        duplicate_flags = any(len(form.getlist(key)) > 1 for key in optional_fields)
        if len(form.getlist("file")) != 1 or invalid_flags or duplicate_flags:
            raise ApiError(
                422,
                "INVALID_REQUEST",
                "Expected one file and optional FastGPT parser flags as boolean strings",
            )
        path: Path | None = None
        try:
            path, size = await _save_upload(file, app_settings)
            request.state.file_size = size
            pages = _inspect_pdf(path, app_settings)
            request.state.pages = pages
            try:
                async with app.state.request_gate:
                    result: ProviderResult = await driver.parse(path)
                request.state.upstream_status = result.upstream_status
            except QueueFullError as exc:
                raise ApiError(
                    503,
                    "PARSER_BUSY",
                    "The parser service is busy; retry the request later",
                    headers={"Retry-After": "5"},
                ) from exc
            except QueueTimeoutError as exc:
                raise ApiError(
                    503,
                    "QUEUE_TIMEOUT",
                    "The request waited too long for the parser service",
                    headers={"Retry-After": "5"},
                ) from exc
            except ProviderTimeout as exc:
                raise ApiError(
                    504,
                    "CORE_TIMEOUT",
                    "The parser service did not finish within the timeout",
                ) from exc
            except ProviderUnavailable as exc:
                raise ApiError(
                    503,
                    "CORE_UNAVAILABLE",
                    "The parser service is not ready",
                ) from exc
            except ProviderProcessingError as exc:
                request.state.upstream_status = exc.status_code or "-"
                raise ApiError(
                    502,
                    "CORE_PARSE_FAILED",
                    "The parser service failed",
                ) from exc
            except ProviderProtocolError as exc:
                raise ApiError(
                    502,
                    "CORE_PARSE_FAILED",
                    "The parser service returned an invalid response",
                ) from exc
            except Exception as exc:
                logger.exception(
                    "parse_internal_error request_id=%s error_type=%s",
                    getattr(request.state, "request_id", "-"),
                    type(exc).__name__,
                )
                raise ApiError(
                    500,
                    "INTERNAL_ERROR",
                    "The parser encountered an internal error",
                ) from exc
            try:
                markdown = rewrite_images(result.markdown, result.images)
            except ImageRewriteError as exc:
                raise ApiError(
                    502,
                    "IMAGE_CONVERSION_FAILED",
                    "The parser service returned unusable image data",
                ) from exc
            return {
                "success": True,
                "message": "",
                "pages": pages,
                "markdown": markdown,
            }
        finally:
            if path is not None:
                path.unlink(missing_ok=True)

    return app


app = create_app()
