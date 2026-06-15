#!/bin/bash
# Script to install VeraPDF in the Docker container
# Run this inside the container: docker exec orion_module_api /app/setup-verapdf.sh

set -e

echo "Installing VeraPDF..."

VERAPDF_DIR="/opt/verapdf"
VERAPDF_VERSION="1.31.79"
VERAPDF_URL_PRIMARY="https://github.com/veraPDF/veraPDF-apps/releases/download/v${VERAPDF_VERSION}/verapdf-greenfield-${VERAPDF_VERSION}-linux.zip"
VERAPDF_URL_FALLBACK="https://github.com/veraPDF/veraPDF-apps/releases/download/v${VERAPDF_VERSION}/verapdf-greenfield-${VERAPDF_VERSION}.zip"

mkdir -p ${VERAPDF_DIR}
cd /tmp

echo "Downloading VeraPDF v${VERAPDF_VERSION}..."
if ! curl -fL -o verapdf.zip "${VERAPDF_URL_PRIMARY}"; then
    echo "Primary download URL failed, trying fallback..."
    curl -fL -o verapdf.zip "${VERAPDF_URL_FALLBACK}" || {
        echo "Failed to download VeraPDF"
        exit 1
    }
fi

echo "Extracting VeraPDF..."
unzip -q verapdf.zip -d ${VERAPDF_DIR}

echo "Setting permissions..."
find ${VERAPDF_DIR} -name "verapdf" -type f -exec chmod +x {} \;

VERAPDF_BIN=$(find ${VERAPDF_DIR} -name "verapdf" -type f | head -1)
if [ -z "${VERAPDF_BIN}" ]; then
    echo "VeraPDF executable not found after extraction"
    exit 1
fi

ln -sf "${VERAPDF_BIN}" /usr/local/bin/verapdf

echo "Cleaning up..."
rm verapdf.zip

echo "VeraPDF installed successfully!"
echo "Executable location: ${VERAPDF_BIN}"
