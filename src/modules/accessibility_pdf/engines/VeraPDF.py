from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from typing import Any

from src.core.config import settings


class VeraPDF:
    """Simple PDF validator engine.

    Keeps validation logic outside the router and returns a compact result payload.
    """

    def validate_pdf(self, file_bytes: bytes, filename: str) -> dict[str, Any]:
        if not file_bytes:
            raise ValueError("Uploaded file is empty")

        command_path, attempted_paths = self._resolve_verapdf_command(settings.verapdf_command)
        if not command_path:
            attempted = ", ".join(attempted_paths)
            raise ValueError(
                f"VeraPDF command not found. Attempted: {attempted}. "
                f"Please ensure VeraPDF is installed or set the correct VERAPDF_COMMAND in .env"
            )

        suffix = os.path.splitext(filename or "document.pdf")[1] or ".pdf"
        if suffix.lower() != ".pdf":
            suffix = ".pdf"

        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_file.write(file_bytes)
                temp_path = temp_file.name

            process = subprocess.run(
                [command_path, "--format", "json", temp_path],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )

            if process.returncode != 0 and not process.stdout.strip():
                error_message = process.stderr.strip() or "VeraPDF command failed"
                raise ValueError(error_message)

            return self._parse_verapdf_json(process.stdout, process.stderr)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("VeraPDF validation timed out") from exc
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

    @staticmethod
    def _resolve_verapdf_command(configured_command: str | None) -> tuple[str | None, list[str]]:
        attempted: list[str] = []

        def _try_path(candidate: str | None) -> str | None:
            if not candidate:
                return None

            value = candidate.strip()
            if not value:
                return None

            attempted.append(value)

            # If candidate is an executable name, resolve from PATH.
            if os.path.sep not in value and "/" not in value:
                resolved = shutil.which(value)
                if resolved:
                    return resolved

            if os.path.exists(value):
                return value

            return None

        # 1) Explicit command from settings/env
        resolved = _try_path(configured_command)
        if resolved:
            return resolved, attempted

        # 2) Common executable names from PATH
        for name in ("verapdf", "verapdf.bat"):
            resolved = _try_path(name)
            if resolved:
                return resolved, attempted

        return None, attempted

    @staticmethod
    def _parse_verapdf_json(stdout: str, stderr: str) -> dict[str, Any]:
        stdout = (stdout or "").strip()
        if not stdout:
            raise ValueError(stderr.strip() or "Empty response from VeraPDF")

        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            # Some VeraPDF distributions prepend logs before JSON; extract the JSON body.
            start = stdout.find("{")
            end = stdout.rfind("}")
            if start == -1 or end == -1 or end <= start:
                raise ValueError("Unable to parse VeraPDF JSON output")

            try:
                return json.loads(stdout[start : end + 1])
            except json.JSONDecodeError as exc:
                raise ValueError("Unable to parse VeraPDF JSON output") from exc
