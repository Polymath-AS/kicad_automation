ARG KICAD_AUTO_IMAGE=ghcr.io/inti-cmnb/kicad9_auto:1.9.0@sha256:5c7875356c8d96d4f8e562df958c809eb1731d582a3c784ebeb96aa939aa4f32
FROM ${KICAD_AUTO_IMAGE}

USER root
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      git jq poppler-utils python3 python3-yaml unzip xauth zip \
 && rm -rf /var/lib/apt/lists/*

COPY docker/bin/kicad-toolchain /usr/local/bin/kicad-toolchain
COPY skills/kicad-drc/scripts/summarize_checks.py /opt/kicad-automation/summarize_checks.py
RUN chmod 0755 /usr/local/bin/kicad-toolchain

WORKDIR /work
ENTRYPOINT ["kicad-toolchain"]
CMD ["doctor"]
