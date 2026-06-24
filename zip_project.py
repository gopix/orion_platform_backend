import os
import zipfile
from datetime import datetime

# Folder to zip
SOURCE_DIR = r"C:\Orion\codebase\orion_backend"

# Folders to exclude
EXCLUDE_DIRS = {
    "venv",
    "verapdf-installer",
    "pdfix_sdk-9.0.0",
    "__pycache__",
    ".git"
}

# Files to exclude (optional)
EXCLUDE_FILES = {
    ".env"
}

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
zip_filename = f"orion_backend_{timestamp}.zip"

with zipfile.ZipFile(zip_filename, "w", zipfile.ZIP_DEFLATED) as zipf:
    for root, dirs, files in os.walk(SOURCE_DIR):

        # Remove excluded directories from traversal
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

        for file in files:
            if file in EXCLUDE_FILES:
                continue

            filepath = os.path.join(root, file)

            # Relative path inside ZIP
            arcname = os.path.relpath(filepath, SOURCE_DIR)

            zipf.write(filepath, arcname)

print(f"ZIP created: {zip_filename}")