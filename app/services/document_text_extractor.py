from pathlib import Path

from docx import Document as DocxDocument
from pypdf import PdfReader


PDF_EXTENSIONS = frozenset({".pdf"})
DOCX_EXTENSIONS = frozenset({".docx"})
PDF_MIME_TYPE = "application/pdf"
DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class UnsupportedDocumentTypeError(Exception):
    pass


class DocumentTextExtractionError(Exception):
    pass


class DocumentTextExtractor:
    def extract_text(self, file_path: str | Path, content_type: str | None = None) -> str | None:
        path = Path(file_path)
        suffix = path.suffix.lower()
        if suffix in PDF_EXTENSIONS or content_type == PDF_MIME_TYPE:
            return self.extract_pdf_text(path)
        if suffix in DOCX_EXTENSIONS or content_type == DOCX_MIME_TYPE:
            return self.extract_docx_text(path)
        return None

    def extract_pdf_text(self, file_path: str | Path) -> str:
        try:
            reader = PdfReader(str(file_path))
            pages = [page.extract_text() or "" for page in reader.pages]
        except Exception as exc:
            raise DocumentTextExtractionError("Could not extract text from PDF") from exc
        return _normalize_text("\n".join(pages))

    def extract_docx_text(self, file_path: str | Path) -> str:
        try:
            document = DocxDocument(str(file_path))
            parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text]
            for table in document.tables:
                for row in table.rows:
                    row_text = "\t".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                    if row_text:
                        parts.append(row_text)
        except Exception as exc:
            raise DocumentTextExtractionError("Could not extract text from DOCX") from exc
        return _normalize_text("\n".join(parts))


def _normalize_text(value: str) -> str:
    lines = [line.strip() for line in value.replace("\r\n", "\n").split("\n")]
    return "\n".join(line for line in lines if line)
