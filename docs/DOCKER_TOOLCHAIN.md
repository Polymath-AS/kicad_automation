# Dockerized KiCad 10 Runtime

The runtime is one Docker image based on `ghcr.io/inti-cmnb/kicad10_auto:1.9.0`. That upstream image provides KiCad `10.0.4`, `kicad-cli`, KiBot, KiAuto, KiKit, iBOM, KiBoM, KiCost, and related automation tools. This repository layers only Xvfb/runtime glue, `kicad-mcp-pro`, and the `kicad-cli` validation wrapper.

Normal startup is:

```text
kicad-runtime
  -> configure /config/kicad/10.0/kicad_common.json
  -> start Xvfb on :99
  -> launch pcbnew with a /workspace board
  -> wait for /runtime/tmp/kicad/api.sock
  -> complete the KiCad first-run dialog inside Xvfb when needed
  -> probe the `ipc:///runtime/tmp/kicad/api.sock` endpoint until the board responds
  -> start kicad-mcp-pro on 127.0.0.1:3334/mcp
  -> verify MCP initialize succeeds
```

`api.enable_server` is generated deterministically in `kicad_common.json`. If KiCad 10 still
needs its first-run library setup, `xdotool` completes that dialog inside Xvfb; no host GUI or
human preference click is required. The filesystem socket path used by KiCad is converted to
the `ipc://` URI required by kipy before MCP Pro starts.

Before pcbnew starts, runtime lock files are inspected. A lock owned by `root` on a Docker-shaped
12-hex-character hostname is treated as stale container state and removed. Other locks stop
startup with a project-lock error.

Paths:

| Path | Purpose |
|---|---|
| `/workspace` | Mounted KiCad repository |
| `/runtime` | IPC sockets, process logs, validation reports |
| `/config` | KiCad configuration and HOME |
| `/cache` | KiCad caches |

Build and run:

```powershell
docker compose build
docker compose up kicad
```

Run integration tests:

```powershell
docker compose run --rm test
```

Validation and exports use `/usr/local/bin/validate-kicad`; pass `--erc`, `--drc`,
`--gerbers`, `--drill`, `--pdf`, or `--bom`, or use `--all`.

The image intentionally does not include the old KiCad 9 automation flow, SWIG PCB edit wrapper, repo-owned MCP server, or Freerouting sidecar.
