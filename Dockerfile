# Base image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install Java (required for VeraPDF) and dependencies
RUN apt-get update && apt-get install -y \
    openjdk-21-jre-headless \
    unzip \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install VeraPDF binary in image from local bundled ZIP (offline build)
COPY verapdf-installer/verapdf-installer.zip /tmp/verapdf-installer.zip
RUN mkdir -p /tmp/verapdf-installer-src /opt/verapdf && \
    unzip -q /tmp/verapdf-installer.zip -d /tmp/verapdf-installer-src && \
    VERAPDF_JAR="$(find /tmp/verapdf-installer-src -name 'verapdf-izpack-installer-*.jar' | head -n 1)" && \
    test -n "$VERAPDF_JAR" && \
    printf '#veraPDF Software\n\n#install_dir\nINSTALL_PATH=/opt/verapdf\n' > /tmp/verapdf-install.options && \
    java -jar "$VERAPDF_JAR" -options /tmp/verapdf-install.options && \
    VERAPDF_BIN="$(find /opt/verapdf -name verapdf -type f | head -n 1)" && \
    test -n "$VERAPDF_BIN" && \
    chmod +x "$VERAPDF_BIN" && \
    ln -sf "$VERAPDF_BIN" /usr/local/bin/verapdf && \
    rm -rf /tmp/verapdf-installer.zip /tmp/verapdf-installer-src /tmp/verapdf-install.options

# Copy requirements first (for caching)
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy PDFix SDK
COPY pdfix_sdk-9.0.0/ /opt/pdfix_sdk/

# Copy full project
COPY . .

# Set VeraPDF executable in PATH and PDFix SDK path
ENV PATH="/usr/local/bin:${PATH}"
ENV VERAPDF_COMMAND=/usr/local/bin/verapdf
ENV PDFIX_SDK_PATH=/opt/pdfix_sdk

# Expose port
EXPOSE 8000

# Run FastAPI app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]