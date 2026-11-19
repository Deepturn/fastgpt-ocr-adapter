from __future__ import annotations

import io
import zipfile

import pytest

from fastgpt_ocr_adapter.errors import ProviderProtocolError
from fastgpt_ocr_adapter.providers import mineru_archive


def zipped(entries: dict[str, bytes]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return output.getvalue()


@pytest.mark.parametrize(
    "content",
    [
        b"not a ZIP",
        zipped({"other.md": b"hello"}),
        zipped({"markdown.md": b"\xff"}),
        zipped({"markdown.md": b"hello", "images/broken.png": b"not an image"}),
        zipped({"markdown.md": b"hello", "images/../file.jpg": b"\xff\xd8\xff"}),
    ],
)
def test_rejects_invalid_archive(content: bytes) -> None:
    with pytest.raises(ProviderProtocolError):
        mineru_archive.decode_mineru_archive(content, 200)


def test_archive_rejects_oversize_before_decompression(monkeypatch) -> None:
    monkeypatch.setattr(mineru_archive, "_MAX_IMAGE_BYTES", 4)
    content = zipped({"markdown.md": b"hi", "images/file.png": b"\x89PNG\r\n\x1a\n"})
    with pytest.raises(ProviderProtocolError, match="decoded size"):
        mineru_archive.decode_mineru_archive(content, 200)


def test_archive_accepts_empty_images_directory() -> None:
    result = mineru_archive.decode_mineru_archive(
        zipped({"markdown.md": b"hello", "images/": b"", "middle_json.json": b"{}"}), 200
    )
    assert result.markdown == "hello"
    assert result.images == {}
