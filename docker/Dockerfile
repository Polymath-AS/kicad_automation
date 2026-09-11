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

RUN /opt/kicad-mcp-pro/bin/python -m pip install --no-cache-dir "Pillow==12.3.0" \
 && command -v rsvg-convert

COPY docker/patches/kicad-mcp-pro-3.34.0-kicad10-pad-lookup.patch /tmp/kicad-mcp-pro.patch
COPY docker/patches/kicad-mcp-pro-3.34.0-layer-aliases.patch /tmp/kicad-mcp-pro-layers.patch
COPY docker/patches/kicad-mcp-pro-3.34.0-qualified-footprint.patch /tmp/kicad-mcp-pro-footprint.patch
COPY docker/patches/kicad-mcp-pro-3.34.0-pcb-visual-review.patch /tmp/kicad-mcp-pro-pcb-visual-review.patch
COPY docker/tests/verify_kicad_mcp_compat.py /tmp/verify-kicad-mcp-compat.py
COPY scripts/pcb_visual_review.py /opt/kicad-mcp-pro/lib/python3.13/site-packages/kicad_mcp/tools/pcb_visual_review.py
COPY tests/test_pcb_visual_review.py /tmp/test_pcb_visual_review.py

RUN patch --batch --fuzz=0 -p1 \
      -d /opt/kicad-mcp-pro/lib/python3.13/site-packages \
      </tmp/kicad-mcp-pro.patch \
 && patch --batch --fuzz=0 -p1 \
      -d /opt/kicad-mcp-pro/lib/python3.13/site-packages \
      </tmp/kicad-mcp-pro-layers.patch \
 && patch --batch --fuzz=0 -p1 \
      -d /opt/kicad-mcp-pro/lib/python3.13/site-packages \
      </tmp/kicad-mcp-pro-footprint.patch \
 && patch --batch --fuzz=0 -p1 \
      -d /opt/kicad-mcp-pro/lib/python3.13/site-packages \
      </tmp/kicad-mcp-pro-pcb-visual-review.patch \
 && /opt/kicad-mcp-pro/bin/python /tmp/verify-kicad-mcp-compat.py \
 && /opt/kicad-mcp-pro/bin/python /tmp/test_pcb_visual_review.py \
 && rm -f /tmp/kicad-mcp-pro.patch /tmp/kicad-mcp-pro-layers.patch \
      /tmp/kicad-mcp-pro-footprint.patch \
      /tmp/kicad-mcp-pro-pcb-visual-review.patch \
      /tmp/test_pcb_visual_review.py \
      /tmp/verify-kicad-mcp-compat.py

COPY docker/bin/kicad-runtime /usr/local/bin/kicad-runtime
COPY docker/bin/run-kicad-integration-tests /usr/local/bin/run-kicad-integration-tests
COPY docker/bin/validate-kicad /usr/local/bin/validate-kicad
COPY scripts/validate-kicad.sh /usr/local/lib/kicad-automation/validate-kicad.sh
COPY scripts/summarize_kicad_report.py /usr/local/lib/kicad-automation/summarize-kicad-report.py
COPY scripts/kicad_mcp_client.py /usr/local/lib/kicad-automation/kicad_mcp_client.py
COPY tests/integration_visual_review.py /usr/local/lib/kicad-automation/integration_visual_review.py
COPY scripts/kicad_contracts.py /usr/local/lib/kicad-automation/kicad_contracts.py
COPY scripts/pad_to_pad_regression.py /usr/local/lib/kicad-automation/pad_to_pad_regression.py
COPY scripts/kicad_topology.py /usr/local/lib/kicad-automation/kicad_topology.py
COPY scripts/kicad_placement.py /usr/local/lib/kicad-automation/kicad_placement.py
COPY scripts/kicad_schematic.py /usr/local/lib/kicad-automation/kicad_schematic.py
COPY scripts/kicad_promotion.py /usr/local/lib/kicad-automation/kicad_promotion.py
COPY scripts/kicad_live_adapter.py /usr/local/lib/kicad-automation/kicad_live_adapter.py
COPY scripts/kicad_live_promotion.py /usr/local/lib/kicad-automation/kicad_live_promotion.py
COPY scripts/kicad_live_placement.py /usr/local/lib/kicad-automation/kicad_live_placement.py

RUN sed -i 's/\r$//' \
      /usr/local/bin/kicad-runtime \
      /usr/local/bin/run-kicad-integration-tests /usr/local/bin/validate-kicad \
      /usr/local/lib/kicad-automation/validate-kicad.sh \
      /usr/local/lib/kicad-automation/summarize-kicad-report.py \
      /usr/local/lib/kicad-automation/kicad_mcp_client.py \
      /usr/local/lib/kicad-automation/kicad_contracts.py \
      /usr/local/lib/kicad-automation/pad_to_pad_regression.py \
      /usr/local/lib/kicad-automation/kicad_topology.py \
      /usr/local/lib/kicad-automation/kicad_placement.py \
      /usr/local/lib/kicad-automation/kicad_schematic.py \
      /usr/local/lib/kicad-automation/kicad_promotion.py \
      /usr/local/lib/kicad-automation/kicad_live_adapter.py \
      /usr/local/lib/kicad-automation/kicad_live_promotion.py \
      /usr/local/lib/kicad-automation/kicad_live_placement.py \
 && chmod 0755 /usr/local/bin/kicad-runtime \
      /usr/local/bin/run-kicad-integration-tests /usr/local/bin/validate-kicad \
      /usr/local/lib/kicad-automation/validate-kicad.sh \
      /usr/local/lib/kicad-automation/summarize-kicad-report.py \
 && ln -sf /usr/bin/fdfind /usr/local/bin/fd

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    KICAD_WORKSPACE=/workspace \
    KICAD_MCP_WORKSPACE_ROOT=/workspace \
    KICAD_VALIDATE=/usr/local/bin/validate-kicad \
    KICAD_MCP_PROJECT_DIR=/workspace \
    KICAD_MCP_PROFILE=builder \
    KICAD_MCP_SCHEMATIC_MODE=file_backed \
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
