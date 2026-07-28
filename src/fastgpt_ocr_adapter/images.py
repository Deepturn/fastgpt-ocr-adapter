from __future__ import annotations

import base64
import binascii
import re
from urllib.parse import unquote, urlparse


class ImageRewriteError(ValueError):
    pass


_MARKDOWN_IMAGE = re.compile(
    r"(?P<prefix>!\[[^\]]*\]\(\s*)(?P<target><[^>]+>|[^\s)]+)"
    r"(?P<suffix>\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))?\s*\)",
    flags=re.IGNORECASE,
)
_HTML_IMAGE = re.compile(
    r"(?P<prefix><img\b[^>]*?\bsrc\s*=\s*[\"'])(?P<target>[^\"']+)"
    r"(?P<suffix>[\"'])",
    flags=re.IGNORECASE,
)


def image_data_uri(encoded: str) -> str:
    if not isinstance(encoded, str):
        raise ImageRewriteError("The parser returned non-text image data")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageRewriteError("The parser returned invalid base64 image data") from exc
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif raw.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    else:
        raise ImageRewriteError("The parser returned an unsupported image type")
    return f"data:{mime};base64,{encoded}"


def _validate_data_uri(value: str) -> None:
    match = re.fullmatch(
        r"data:(image/(?:png|jpeg));base64,(?P<data>[A-Za-z0-9+/]*={0,2})",
        value,
    )
    if match is None:
        raise ImageRewriteError("The parser returned an invalid image data URI")
    image_data_uri(match.group("data"))


def _normalise_key(value: str) -> str:
    return unquote(value.strip().strip("<>")).removeprefix("./")


def _image_map(images: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in images.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ImageRewriteError("The parser returned an invalid image map")
        _validate_data_uri(value)
        clean = _normalise_key(key)
        bare = clean.removeprefix("images/")
        for variant in {clean, bare, f"images/{bare}"}:
            result[variant] = value
    return result


def _is_external(reference: str) -> bool:
    parsed = urlparse(reference)
    return parsed.scheme.lower() in {"data", "http", "https"}


def rewrite_images(markdown: str, images: dict[str, str]) -> str:
    if not isinstance(markdown, str):
        raise ImageRewriteError("The parser did not return markdown text")
    image_map = _image_map(images)

    def replace(match: re.Match[str]) -> str:
        original = match.group("target")
        clean = _normalise_key(original)
        if _is_external(clean):
            return match.group(0)
        replacement = image_map.get(clean) or image_map.get(clean.removeprefix("images/"))
        if replacement is None:
            raise ImageRewriteError(f"The parser did not return image data for {original}")
        suffix = match.groupdict().get("suffix") or ""
        if match.re is _MARKDOWN_IMAGE:
            return f"{match.group('prefix')}{replacement}{suffix})"
        return f"{match.group('prefix')}{replacement}{suffix}"

    rewritten = _MARKDOWN_IMAGE.sub(replace, markdown)
    return _HTML_IMAGE.sub(replace, rewritten)
