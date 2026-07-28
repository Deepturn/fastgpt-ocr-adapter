from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfWriter


def build_pdf(pages: int = 1, *, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    if encrypted:
        writer.encrypt("secret")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.fixture
def pdf_bytes() -> bytes:
    return build_pdf()
