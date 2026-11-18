"""FileTypeDetector — determine a document's format.

Answers "what kind of document is this?" from a filename and/or its bytes, so the
parser layer (and a future parser factory) can route to the right provider. Uses
the extension when available and falls back to magic-byte sniffing (PDF signature,
and ZIP-container inspection to tell DOCX from EPUB). Stateless and pure: no I/O
beyond reading the bytes handed to it.
"""
import io
import zipfile
from typing import Optional

from src.modules.book_forge.ai.intelligence.parsers.models import DocumentFormat

_EXTENSION_MAP = {
    "pdf": DocumentFormat.PDF,
    "docx": DocumentFormat.DOCX,
    "epub": DocumentFormat.EPUB,
}


class FileTypeDetector:
    """Detect a :class:`DocumentFormat` from a filename or raw bytes."""

    @staticmethod
    def detect(
        *, filename: Optional[str] = None, data: Optional[bytes] = None
    ) -> DocumentFormat:
        """Detect the format, preferring the extension, then the bytes."""
        if filename:
            fmt = FileTypeDetector.from_extension(filename)
            if fmt is not DocumentFormat.UNKNOWN:
                return fmt
        if data is not None:
            return FileTypeDetector.from_bytes(data)
        return DocumentFormat.UNKNOWN

    @staticmethod
    def from_extension(filename: str) -> DocumentFormat:
        """Map a filename's extension to a format."""
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return _EXTENSION_MAP.get(ext, DocumentFormat.UNKNOWN)

    @staticmethod
    def from_bytes(data: bytes) -> DocumentFormat:
        """Sniff the format from leading magic bytes / container contents."""
        if data.startswith(b"%PDF"):
            return DocumentFormat.PDF
        # DOCX and EPUB are both ZIP containers — look inside to disambiguate.
        if data.startswith(b"PK\x03\x04"):
            return FileTypeDetector._inspect_zip(data)
        return DocumentFormat.UNKNOWN

    @staticmethod
    def _inspect_zip(data: bytes) -> DocumentFormat:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                names = set(zf.namelist())
                if "word/document.xml" in names:
                    return DocumentFormat.DOCX
                if "mimetype" in names:
                    mimetype = zf.read("mimetype").strip()
                    if mimetype == b"application/epub+zip":
                        return DocumentFormat.EPUB
        except (zipfile.BadZipFile, KeyError, OSError):
            pass
        return DocumentFormat.UNKNOWN
