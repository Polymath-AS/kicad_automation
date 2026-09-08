# KiCad 10 MCP Automation

This repository provides a reproducible Docker runtime for agent-driven KiCad work:

```text
Codex
  -> kicad-mcp-pro over Streamable HTTP
  -> KiCad 10 IPC / kipy
  -> pcbnew running under Xvfb

kicad-cli
  -> ERC, DRC, exports, validation
```

The old KiCad 9 worker, repo-owned MCP server, SWIG `pcbnew` editor, wrapper aliases, and duplicate validation paths have been removed. The active architecture is KiCad MCP Pro plus the bundled tools from `ghcr.io/inti-cmnb/kicad10_auto:1.9.0`.

## Build

```powershell
docker compose build
```

The image pins:

- `ghcr.io/inti-cmnb/kicad10_auto:1.9.0`, which ships KiCad `10.0.4` and the KiCad automation tool bundle.
- `kicad-mcp-pro==3.34.0`, installed in `/opt/kicad-mcp-pro`.

## Run

```powershell
docker compose up kicad
```

By default this opens `tests/fixtures/kicad-project/minimal.kicad_pcb`. To run against another mounted project:

```powershell
$env:KICAD_ENTRYPOINT_PROJECT = "CAD/my-board/my-board.kicad_pcb"
docker compose up kicad
```

The project is mounted at `/workspace`. Runtime sockets and logs live under `/runtime`; KiCad config is under `/config`; caches are under `/cache`.

MCP Pro is published only to host loopback:

```text
http://127.0.0.1:3334/mcp
```

Codex project config example:

```toml
[mcp_servers.kicad]
url = "http://127.0.0.1:3334/mcp"
tool_timeout_sec = 120
```

## MCP Surface

Use KiCad MCP Pro tool names directly. The default `pcb_only` profile exposes the live PCB
workflow, including:

`kicad_get_server_info`, `kicad_get_project_info`, `kicad_get_version`, `pcb_get_board_summary`,
`pcb_get_footprints`, `pcb_get_nets`, `pcb_get_tracks`, `pcb_get_shapes`,
`pcb_move_component`, `pcb_move_footprint`, `pcb_route_trace`, and `pcb_save`.

The default profile is `pcb_only` with `KICAD_MCP_OPERATING_MODE=write`. Set
`KICAD_MCP_PROFILE=pcb_layout`, `manufacturing`, or another upstream MCP Pro profile in `.env`
when that profile's additional tools are required.

## Validate

`kicad-cli` is the validation/export authority. The primary entry point is:

```powershell
docker compose run --rm kicad validate --project /workspace/tests/fixtures/kicad-project/minimal --erc --drc
docker compose run --rm kicad validate --project /workspace/CAD/my-board/my-board --all
```

The script supports ERC, DRC, Gerbers, drill files, schematic/PCB PDFs, and BOM export.
It exits nonzero when ERC/DRC report violations or when an export/check tool fails.

## Test

```powershell
docker compose run --rm test
```

The integration path verifies KiCad 10.x, Xvfb, `DISPLAY`, pcbnew launch, IPC socket creation, MCP Pro startup, MCP tool discovery, an IPC-required PCB query, board save, DRC, ERC, eeschema launch, and clean process shutdown.

PowerShell convenience wrapper:

```powershell
.\tools\kicad-docker.ps1 build
.\tools\kicad-docker.ps1 test
.\tools\kicad-docker.ps1 validate tests/fixtures/kicad-project/minimal --erc --drc
```
