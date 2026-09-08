FROM ghcr.io/inti-cmnb/kicad10_auto:1.9.0@sha256:493666a06d900ed3352c50b0f75a76ccdfe194999c097d455021cab9e3c723fa

ARG DEBIAN_FRONTEND=noninteractive
ARG KICAD_MCP_PRO_VERSION=3.34.0

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl dbus-x11 fd-find file git jq make mesa-utils \
      patch poppler-utils python3-pip python3-venv ripgrep rsync sqlite3 tree unzip \
      x11-utils xauth xdotool xvfb yq zip \
 && python3 -m venv /opt/kicad-mcp-pro \
 && /opt/kicad-mcp-pro/bin/python -m pip install --upgrade --no-cache-dir pip \
 && /opt/kicad-mcp-pro/bin/python -m pip install --no-cache-dir "kicad-mcp-pro[http]==${KICAD_MCP_PRO_VERSION}" \
 && ln -sf /opt/kicad-mcp-pro/bin/kicad-mcp-pro /usr/local/bin/kicad-mcp-pro \
 && rm -rf /var/lib/apt/lists/*

COPY docker/bin/kicad-runtime /usr/local/bin/kicad-runtime
COPY docker/bin/run-kicad-integration-tests /usr/local/bin/run-kicad-integration-tests
COPY docker/bin/validate-kicad /usr/local/bin/validate-kicad
COPY scripts/validate-kicad.sh /usr/local/lib/kicad-automation/validate-kicad.sh

RUN chmod 0755 /usr/local/bin/kicad-runtime \
      /usr/local/bin/run-kicad-integration-tests /usr/local/bin/validate-kicad \
      /usr/local/lib/kicad-automation/validate-kicad.sh \
 && ln -sf /usr/bin/fdfind /usr/local/bin/fd

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    KICAD_WORKSPACE=/workspace \
    KICAD_VALIDATE=/usr/local/bin/validate-kicad \
    KICAD_MCP_PROJECT_DIR=/workspace \
    KICAD_MCP_PROFILE=pcb_only \
    KICAD_MCP_SCHEMATIC_MODE=disabled \
    KICAD_MCP_OPERATING_MODE=write \
    KICAD_MCP_HOST=0.0.0.0 \
    KICAD_MCP_PORT=3334 \
    KICAD_MCP_MOUNT_PATH=/mcp \
    KICAD_MCP_STATEFUL_HTTP=0 \
    KICAD_MCP_HTTP_BOUNDARY=loopback-proxy \
    KICAD_MCP_PUBLIC_BASE_URL=http://127.0.0.1:3334 \
    KICAD_MCP_AUTH_TOKEN=kicad-automation-local-dev-token-change-me-2026 \
    DISPLAY=:99 \
    LIBGL_ALWAYS_SOFTWARE=1 \
    XDG_CONFIG_HOME=/config \
    XDG_CACHE_HOME=/cache \
    TMPDIR=/runtime/tmp

WORKDIR /workspace
EXPOSE 3334
ENTRYPOINT ["kicad-runtime"]
CMD ["serve", "tests/fixtures/kicad-project/minimal.kicad_pcb"]
