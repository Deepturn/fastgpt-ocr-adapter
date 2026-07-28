from __future__ import annotations

import base64

import pytest

from fastgpt_ocr_adapter.images import (
    ImageRewriteError,
    image_data_uri,
    rewrite_images,
)

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\npayload").decode()
JPEG = base64.b64encode(b"\xff\xd8\xffpayload").decode()


def test_detects_png_and_jpeg() -> None:
    assert image_data_uri(PNG) == f"data:image/png;base64,{PNG}"
    assert image_data_uri(JPEG) == f"data:image/jpeg;base64,{JPEG}"


@pytest.mark.parametrize("value", ["not-base64", base64.b64encode(b"GIF89a").decode(), 123])
def test_invalid_raw_image_is_rejected(value: object) -> None:
    with pytest.raises(ImageRewriteError):
        image_data_uri(value)  # type: ignore[arg-type]


def test_rewrites_marker_and_mineru_image_paths() -> None:
    markdown = (
        "![one](images/one.png \"title\")\n"
        "![two](two.jpg)\n"
        '<img alt="three" src="./images/three.png">'
    )
    result = rewrite_images(
        markdown,
        {
            "one.png": f"data:image/png;base64,{PNG}",
            "two.jpg": f"data:image/jpeg;base64,{JPEG}",
            "images/three.png": f"data:image/png;base64,{PNG}",
        },
    )
    assert "images/one.png" not in result
    assert "](two.jpg)" not in result
    assert "./images/three.png" not in result
    assert result.count("data:image/png;base64") == 2
    assert result.count("data:image/jpeg;base64") == 1
    assert '"title"' in result


def test_external_images_are_left_alone() -> None:
    markdown = (
        "![remote](https://example.com/a.png)\n"
        '<img src="data:image/png;base64,anything">'
    )
    assert rewrite_images(markdown, {}) == markdown


@pytest.mark.parametrize(
    ("markdown", "images"),
    [
        ("![missing](images/no.png)", {}),
        ("![bad](images/a.png)", {"a.png": "data:text/plain;base64,eA=="}),
        ("![bad](images/a.png)", {"a.png": "data:image/png;base64,eA=="}),
        ("![bad](images/a.png)", {1: "data:image/png;base64,eA=="}),
    ],
)
def test_invalid_or_unresolved_images_are_rejected(
    markdown: str,
    images: dict,
) -> None:
    with pytest.raises(ImageRewriteError):
        rewrite_images(markdown, images)
