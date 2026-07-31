from __future__ import annotations

from io import BytesIO

import pytest
from docx import Document

from app.quality_standards.documents import extract_document


def _docx_bytes(*paragraphs: str) -> bytes:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _pdf_bytes(*pages: str) -> bytes:
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{index} 0 R' for index in range(3, 3 + len(pages)))}] /Count {len(pages)} >>".encode(),
    ]
    font_id = 3 + len(pages)
    for index, page in enumerate(pages):
        content = f"BT /F1 12 Tf 72 720 Td ({page}) Tj ET".encode()
        content_id = font_id + 1 + index
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/MediaBox [0 0 612 792] /Contents {content_id} 0 R >>".encode()
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for page in pages:
        content = f"BT /F1 12 Tf 72 720 Td ({page}) Tj ET".encode()
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())
    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode()
    )
    return bytes(output)


def test_extracts_docx_paragraphs_and_hashes_original_content() -> None:
    content = _docx_bytes("服务原则", "主动解决问题")

    result = extract_document("服务标准.docx", content)

    assert result.text == "服务原则\n主动解决问题"
    assert [(section.locator, section.text) for section in result.sections] == [
        ("第 1 段", "服务原则"),
        ("第 2 段", "主动解决问题"),
    ]
    assert len(result.sha256) == 64


def test_extracts_pdf_pages_with_page_locators() -> None:
    result = extract_document("服务标准.pdf", _pdf_bytes("First page", "Second page"))

    assert result.text == "First page\nSecond page"
    assert [(section.locator, section.text) for section in result.sections] == [
        ("第 1 页", "First page"),
        ("第 2 页", "Second page"),
    ]


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("服务标准.docx", _pdf_bytes("PDF content")),
        ("服务标准.pdf", _docx_bytes("DOCX content")),
    ],
)
def test_rejects_filename_that_does_not_match_document_content(filename: str, content: bytes) -> None:
    with pytest.raises(ValueError, match="文件扩展名与实际内容不匹配"):
        extract_document(filename, content)


def test_rejects_document_larger_than_twenty_megabytes() -> None:
    with pytest.raises(ValueError, match="单个文件不能超过 20 MB"):
        extract_document("服务标准.pdf", b"%PDF-" + b"0" * (20 * 1024 * 1024))


@pytest.mark.parametrize(
    ("filename", "content"),
    [
        ("空白.docx", _docx_bytes("")),
        ("扫描件.pdf", _pdf_bytes("")),
    ],
)
def test_rejects_documents_without_extractable_text(filename: str, content: bytes) -> None:
    with pytest.raises(ValueError, match="未提取到可复制的文本"):
        extract_document(filename, content)
