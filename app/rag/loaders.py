"""Ingestion: read documents (PDF, Word, text, Excel) and clean the text.

The original file is never changed; these functions only return its text.
Used for uploaded office documents and, later, the policy documents.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook
from pypdf import PdfReader


# 1. CLEANING
def clean_text(text: str) -> str:
    """Tidy extracted text without changing its words.

    - joins a word split with a hyphen across two lines ("regis-\\ntration")
    - collapses repeated spaces and tabs
    - removes spaces at the ends of lines and empty lines
    """
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


# 2. PDF
def read_pdf(path: str | Path) -> str:
    """Return the text of every page of a PDF."""
    reader = PdfReader(path)
    pages = [page.extract_text() or "" for page in reader.pages]
    return clean_text("\n".join(pages))


# 3. WORD
def read_docx(path: str | Path) -> str:
    """Return the paragraphs and table cells of a Word document, in document order."""
    document = Document(path)
    lines = []
    for block in document.element.body.iterchildren():
        if block.tag.endswith("}p"):                 # a paragraph
            lines.append(Paragraph(block, document).text)
        elif block.tag.endswith("}tbl"):             # a table: one line per cell
            for row in Table(block, document).rows:
                for cell in row.cells:
                    lines.append(cell.text)
    return clean_text("\n".join(lines))


# 4. EXCEL: ONE ROW PER CHILD
MIN_FILLED_CELLS = 3  # titles, blank rows and footers have fewer filled cells than a real row


def read_excel_rows(path: str | Path) -> list[dict[str, Any]]:
    """Return the rows of the first sheet as dictionaries keyed by the column names.

    The header is the first row with at least MIN_FILLED_CELLS filled cells;
    rows above it (titles) and short rows below it (blank lines, footers) are skipped.
    """
    sheet = load_workbook(path, data_only=True).active
    header: list[str] | None = None
    rows = []
    for values in sheet.iter_rows(values_only=True):
        cells = [value.strip() if isinstance(value, str) else value for value in values]
        filled = sum(cell not in (None, "") for cell in cells)
        if filled < MIN_FILLED_CELLS:
            continue
        if header is None:
            header = [str(cell) if cell is not None else f"column_{i}" for i, cell in enumerate(cells, 1)]
        else:
            rows.append(dict(zip(header, cells)))
    return rows


# 5. CHOOSE THE READER FROM THE FILE TYPE
READERS = {".pdf": read_pdf, ".docx": read_docx}


def read_document(path: str | Path) -> str:
    """Read a PDF, Word or plain-text document and return its cleaned text."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Document not found: {path}")
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return clean_text(path.read_text(encoding="utf-8"))
    if suffix not in READERS:
        raise ValueError(f"Unsupported document type: {suffix}")
    return READERS[suffix](path)
