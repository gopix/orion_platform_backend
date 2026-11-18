# Base image
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install Java (required for VeraPDF), Liberation fonts (for font embedding), and utilities
RUN apt-get update && apt-get install -y \
    openjdk-21-jre-headless \
    unzip \
    ca-certificates \
    fonts-liberation \
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
#RUN pip install --no-cache-dir -r requirements.txt


# Install dependencies with increased timeout and retries
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install \
    --timeout=600 \
    --retries=20 \
    -r requirements.txt


# Pre-warm the tiktoken BPE cache at build time. tiktoken downloads its encoding
# files on first use; in a running container that call is often blocked or the
# temp cache is cold, and token_counter.py then silently degrades to a chars/4
# heuristic. Baking the cache in makes token counting work with no runtime egress.
ENV TIKTOKEN_CACHE_DIR=/opt/tiktoken_cache
RUN mkdir -p "$TIKTOKEN_CACHE_DIR" && \
    python -c "import tiktoken; [tiktoken.get_encoding(e) for e in ('cl100k_base', 'o200k_base')]"

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

# Run FastAPI app with extended keep-alive timeout for long-running PDF remediation
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "600"]
