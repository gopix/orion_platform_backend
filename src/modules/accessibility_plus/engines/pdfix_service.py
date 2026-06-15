from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from uuid import uuid4


class PDFixService:
    """PDF remediation service backed by PDFix SDK."""

    def __init__(self) -> None:
        base_temp_dir = Path(__file__).resolve().parents[1] / "temp"
        self.upload_dir = base_temp_dir / "uploads"
        self.remediated_dir = base_temp_dir / "remediated"
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.remediated_dir.mkdir(parents=True, exist_ok=True)

        # Try container path first, then fallback to local Windows path for development
        self.default_sdk_root = Path("/opt/pdfix_sdk/pdfix_sdk-9.0.0")
        if not self.default_sdk_root.exists():
            self.default_sdk_root = Path(r"C:\Users\gopal\Downloads\pdfix_sdk-9.0.0\pdfix_sdk-9.0.0")

    def remediate_pdf(self, file_bytes: bytes, filename: str) -> dict[str, str | int | bool]:
        if not file_bytes:
            raise ValueError("Uploaded file is empty")

        if not filename or not filename.lower().endswith(".pdf"):
            raise ValueError("Only .pdf files are supported")

        pdfix_module = self._load_pdfix_module()

        stem = Path(filename).stem or "document"
        unique_id = uuid4().hex
        upload_path = self.upload_dir / f"{unique_id}_{stem}.pdf"
        remediated_path = self.remediated_dir / f"{unique_id}_{stem}_remediated.pdf"

        upload_path.write_bytes(file_bytes)

        pdfix = pdfix_module.GetPdfix()
        if not pdfix:
            raise ValueError("Unable to initialize PDFix SDK")

        doc = None
        tags_added = False
        page_count = 0
        try:
            doc = pdfix.OpenDoc(str(upload_path), "")
            if not doc:
                raise ValueError(self._get_pdfix_error(pdfix, "Failed to open PDF"))

            page_count = doc.GetNumPages()

            tag_params = pdfix_module.PdfTagsParams()
            tags_added = bool(doc.AddTags(tag_params))

            save_ok = doc.Save(str(remediated_path), pdfix_module.kSaveFull)
            if not save_ok:
                raise ValueError(self._get_pdfix_error(pdfix, "Failed to save remediated PDF"))
        finally:
            if doc:
                doc.Close()

        return {
            "original_filename": filename,
            "remediated_filename": remediated_path.name,
            "upload_path": str(upload_path),
            "remediated_path": str(remediated_path),
            "file_size_bytes": len(file_bytes),
            "page_count": page_count,
            "tags_added": tags_added,
            "engine": "pdfix-sdk",
            "status": "completed",
        }

    def _load_pdfix_module(self):
        try:
            return importlib.import_module("pdfixsdk")
        except ImportError:
            sdk_src_path = self._resolve_sdk_src_path()
            if str(sdk_src_path) not in sys.path:
                sys.path.insert(0, str(sdk_src_path))

            try:
                return importlib.import_module("pdfixsdk")
            except ImportError as exc:
                raise ValueError(
                    "PDFix SDK not available. Install 'pdfix-sdk' or set PDFIX_SDK_PATH to your SDK root."
                ) from exc

    def _resolve_sdk_src_path(self) -> Path:
        configured = os.getenv("PDFIX_SDK_PATH")
        candidates: list[Path] = []

        if configured:
            candidates.append(Path(configured))

        candidates.append(self.default_sdk_root)

        for root in candidates:
            src_path = root / "src"
            if src_path.exists() and (src_path / "pdfixsdk").exists():
                return src_path

        attempted = ", ".join(str(candidate) for candidate in candidates)
        raise ValueError(
            f"Unable to locate PDFix SDK source path. Attempted: {attempted}. "
            "Set PDFIX_SDK_PATH to the folder containing src/pdfixsdk."
        )

    @staticmethod
    def _get_pdfix_error(pdfix, fallback_message: str) -> str:
        try:
            description = pdfix.GetErrorDescription()
            if description:
                return str(description)

            error_message = pdfix.GetError()
            if error_message:
                return str(error_message)
        except Exception:
            return fallback_message

        return fallback_message