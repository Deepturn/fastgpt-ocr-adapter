from __future__ import annotations

import base64
import io
import zipfile
import zlib

from ..errors import ProviderProtocolError
from ..images import ImageRewriteError, image_data_uri
from .base import ProviderResult

_MAX_ENTRIES = 4096
_MAX_MARKDOWN_BYTES = 8 * 1024 * 1024
_MAX_IMAGE_BYTES = 48 * 1024 * 1024


def decode_mineru_archive(content: bytes, upstream_status: int) -> ProviderResult:
    """Read only the Markdown and images from a Tasks default export."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > _MAX_ENTRIES:
                raise ProviderProtocolError("MinerU ZIP has too many entries")
            names = {entry.filename for entry in entries}
            if len(names) != len(entries) or "markdown.md" not in names:
                raise ProviderProtocolError("MinerU ZIP has an invalid Markdown layout")
            markdown = archive.getinfo("markdown.md")
            images = [
                entry
                for entry in entries
                if entry.filename.startswith("images/") and not entry.is_dir()
            ]
            if (
                markdown.file_size > _MAX_MARKDOWN_BYTES
                or sum(entry.file_size for entry in images) > _MAX_IMAGE_BYTES
            ):
                raise ProviderProtocolError("MinerU ZIP exceeds the decoded size limit")
            if any(
                any(part in {"", ".", ".."} for part in entry.filename.split("/"))
                or "\\" in entry.filename
                for entry in images
            ):
                raise ProviderProtocolError("MinerU ZIP has invalid image paths")
            return ProviderResult(
                markdown=archive.read(markdown).decode("utf-8"),
                images={
                    entry.filename: image_data_uri(
                        base64.b64encode(archive.read(entry)).decode("ascii")
                    )
                    for entry in images
                },
                upstream_status=upstream_status,
            )
    except (
        zipfile.BadZipFile,
        UnicodeError,
        ImageRewriteError,
        RuntimeError,
        NotImplementedError,
        OSError,
        EOFError,
        zlib.error,
    ) as exc:
        raise ProviderProtocolError("MinerU returned an invalid result ZIP") from exc
