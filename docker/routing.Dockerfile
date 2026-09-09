# Optional batch router. The live KiCad MCP image remains a separate service.
FROM rust:1.90.0-bookworm AS router-build
ARG KRT_REVISION=529f873d4c4c20493b1fa786cc9b42ce6cce2945
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-numpy \
 && git init /opt/KiCadRoutingTools \
 && git -C /opt/KiCadRoutingTools remote add origin https://github.com/drandyhaas/KiCadRoutingTools.git \
 && git -C /opt/KiCadRoutingTools fetch --depth 1 origin ${KRT_REVISION} \
 && git -C /opt/KiCadRoutingTools checkout --detach FETCH_HEAD \
 && test "$(git -C /opt/KiCadRoutingTools rev-parse HEAD)" = "${KRT_REVISION}"
WORKDIR /opt/KiCadRoutingTools
RUN sha256sum rust_router/Cargo.lock > /tmp/cargo-lock.sha256 \
 && python3 build_router.py --from-source \
 && sha256sum -c /tmp/cargo-lock.sha256 \
 && git rev-parse HEAD > REVISION

FROM local/kicad-automation:10.0.4-mcp-pro
COPY --from=router-build /opt/KiCadRoutingTools /opt/KiCadRoutingTools
RUN python3 -m venv /opt/krt-python \
 && /opt/krt-python/bin/pip install --no-cache-dir numpy==2.2.6 scipy==1.15.3 shapely==2.1.1 Pillow==11.2.1 'mcp==1.26.0' \
 && /opt/krt-python/bin/python /opt/KiCadRoutingTools/py_router/route.py --help >/tmp/krt-help.txt
COPY scripts/kicad_routing.py /opt/krt-adapter/kicad_routing.py
ENV KRT_ROOT=/opt/KiCadRoutingTools KRT_WORKSPACE=/workspace KRT_JOBS=/jobs
WORKDIR /jobs
ENTRYPOINT ["/opt/krt-python/bin/python", "/opt/krt-adapter/kicad_routing.py"]
CMD ["doctor"]
