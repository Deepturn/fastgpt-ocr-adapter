from __future__ import annotations

import asyncio
import logging
import secrets
import tempfile
import time
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import AsyncIterator, Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pypdf import PdfReader
from python_multipart.exceptions import MultipartParseError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile
from starlette.exceptions import HTTPException

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
_FASTGPT_FLAGS = frozenset({
    "keep_header_footer", "keep_appendix", "image_analysis", "chart_analysis",
})


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
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    if total == 0:
        path.unlink(missing_ok=True)
        raise ApiError(400, "EMPTY_FILE", "The uploaded PDF is empty")
    return path, total


def _invalid_upload() -> ApiError:
    return ApiError(
        422, "INVALID_REQUEST",
        "Expected one PDF field named file and optional FastGPT parser flags as boolean strings",
    )


def _get_upload(form: FormData) -> UploadFile:
    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise _invalid_upload()
    seen = {"file"}
    for key, value in form.multi_items():
        if key == "file":  # The multipart parser enforces at most one uploaded file.
            if value is not upload:
                raise _invalid_upload()
        elif key in seen or key not in _FASTGPT_FLAGS or value not in ("true", "false"):
            raise _invalid_upload()
        else:
            seen.add(key)
    return upload


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


async def _wait_mineru_retry(delay: float) -> None:
    await asyncio.sleep(delay)


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

        async def resolve_mineru() -> bool:
            nonlocal selected_provider, detection_error
            try:
                driver = await detect_mineru(app_settings)
            except ProviderConfigurationError as exc:
                detection_error = str(exc)
                return False
            selected_provider = app.state.provider = driver
            return True

        async def retry_mineru() -> None:
            delay = 1.0
            while True:
                await _wait_mineru_retry(delay)
                if await resolve_mineru():
                    return
                delay = min(delay * 2, 30.0)

        retry_task = None
        try:
            if auto and selected_provider is None:
                detection_error = "MinerU profile has not been resolved"
                if not await resolve_mineru():
                    retry_task = asyncio.create_task(retry_mineru(), name="mineru-detection")
            yield
        finally:
            try:
                if retry_task is not None:
                    retry_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await retry_task
            finally:
                if selected_provider is not None:
                    await selected_provider.close()
                    if auto and provider is None:
                        selected_provider = app.state.provider = None

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
    async def parse_file(request: Request) -> dict[str, object]:
        _auth_error(app_settings, request)
        driver = selected_provider
        if driver is None:
            raise ApiError(503, "CORE_UNAVAILABLE", "MinerU profile has not been resolved")
        path: Path | None = None
        try:
            # Parse only after auth. The context owns all Starlette spool files.
            try:
                async with request.form(
                    max_files=1, max_fields=len(_FASTGPT_FLAGS), max_part_size=1024,
                ) as form:
                    path, size = await _save_upload(_get_upload(form), app_settings)
            except (HTTPException, MultipartParseError) as exc:
                raise _invalid_upload() from exc
            request.state.file_size = size
            pages = await run_in_threadpool(_inspect_pdf, path, app_settings)
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
                markdown = await run_in_threadpool(rewrite_images, result.markdown, result.images)
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
