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

The PowerShell wrapper validates the selected project on the host before Compose starts. A
complete target must resolve to matching `.kicad_pro`, `.kicad_sch`, and `.kicad_pcb` files under
`-ProjectRoot`. The host project root is mounted at `/workspace`, so the same resolved target is
passed to KiCad as `/workspace/<relative-project-path>`. This catches a stale selection or a
different mount before Docker validation runs; it does not recreate missing projects.

For example, validate a project from the same host root used by the live service with:

```powershell
.\tools\kicad-docker.ps1 validate tests/fixtures/kicad-project/minimal --erc --drc
```

If Docker itself fails, the wrapper preserves sanitized Compose output under
`.kicad-automation/compose-failures/` and reports the failure class. Authentication tokens are
not written to those reports.

MCP Pro is published only to host loopback:

```text
http://127.0.0.1:3334/mcp
```

Codex reads the project-scoped `.codex/config.toml` only for a trusted project. The local
development bearer token must also be present in the host environment before Codex starts:

```powershell
$env:KICAD_MCP_AUTH_TOKEN = "kicad-automation-local-dev-token-change-me-2026"
```

Restart Codex after configuring the server or changing this environment variable. Verify the
connection with `codex mcp list` and the `/mcp` command in the Codex interface.

Codex project config example:

```toml
[mcp_servers.kicad]
url = "http://127.0.0.1:3334/mcp"
bearer_token_env_var = "KICAD_MCP_AUTH_TOKEN"
required = true
startup_timeout_sec = 60
tool_timeout_sec = 120
default_tools_approval_mode = "writes"
```

## Generate a Project

MCP Pro exposes `kicad_create_new_project` in the default write-enabled profile. Generate a
complete KiCad project directory under the mounted `/workspace`; do not create a PCB-only file:

```text
my-board/
  my-board.kicad_pro
  my-board.kicad_sch
  my-board.kicad_pcb
```

The current runtime opens a board before starting MCP so that live IPC is ready. Bootstrap a new
project while the service is running against the fixture or another existing board, then restart
the service against the generated board:

```powershell
.\tools\kicad-docker.ps1 up `
  -ProjectRoot "C:\Users\fnk\Documents\KiCad\Projects" `
  -Target "my-board/my-board.kicad_pcb"
```

The generated project remains in the mounted host directory. After restarting, use MCP Pro for
inspection/editing and `validate-kicad --erc --drc` before continuing.

## MCP Surface

Use KiCad MCP Pro tool names directly. The default `pcb_only` profile exposes the live PCB
workflow, including:

`kicad_get_server_info`, `kicad_get_project_info`, `kicad_get_version`, `pcb_get_board_summary`,
`pcb_get_footprints`, `pcb_get_nets`, `pcb_get_tracks`, `pcb_get_shapes`,
`pcb_move_component`, `pcb_move_footprint`, `pcb_route_trace`, and `pcb_save`.

The default profile is `pcb_only` with `KICAD_MCP_OPERATING_MODE=write`. Set
`KICAD_MCP_PROFILE=pcb_layout`, `manufacturing`, or another upstream MCP Pro profile in `.env`
when that profile's additional tools are required.

Schematic support is split deliberately:

- KiCad 10.0.4 does not provide a verified schematic-editor IPC surface. The official IPC
  documentation describes KiCad 9/10 IPC as GUI-only and PCB-oriented; the installed `kipy`
  schematic class is marked KiCad 11-only and is incompatible with the bundled KiCad 10
  protobufs. The runtime therefore does not start Eeschema as a false readiness signal.
- `KICAD_MCP_PROFILE=schematic_only` (or another upstream schematic profile) exposes MCP Pro's
  supported file-backed schematic tools. Set `KICAD_MCP_SCHEMATIC_MODE=file_backed` to make that
  intent explicit. Their responses identify `Source: file-backed`.
- `KICAD_MCP_SCHEMATIC_MODE=live` fails early with the exact unsupported-stack diagnosis. It is
  reserved for a future verified KiCad 11+ IPC configuration; it does not silently fall back to
  file editing.

The project-scoped Codex allowlist includes the supported file-backed schematic inspection tools;
restart Codex after changing the server profile so its tool catalog is refreshed.

The integration test records `liveSchematicContext`, `liveSchematicRead`, schematic tool
exposure, and the backend identified by the schematic read. Set
`KICAD_TEST_SCHEMATIC_LIVE=1` only when testing a stack that is expected to provide a real live
schematic document; the test fails if MCP reports a file-backed fallback.

## Validate

`kicad-cli` is the validation/export authority. The primary entry point is:

```powershell
docker compose run --rm kicad validate --project /workspace/tests/fixtures/kicad-project/minimal --erc --drc
docker compose run --rm kicad validate --project /workspace/CAD/my-board/my-board --all
```

The script supports ERC, DRC, Gerbers, drill files, schematic/PCB PDFs, and BOM export.
It emits a JSON result with separate ERC and DRC statuses, report paths, violation counts, the
captured `kicad-cli` log, and an overall status. `clean` is used only when both requested checks
ran and produced no violations. Missing project files, validator execution errors, and reported
ERC/DRC violations return distinct nonzero outcomes.

## Test

```powershell
docker compose run --rm test
```

The integration path verifies KiCad 10.x, Xvfb, `DISPLAY`, pcbnew launch, IPC socket creation,
MCP Pro startup, MCP tool discovery, live PCB queries before and after save, project diagnostics,
schematic capability evidence when a schematic profile is selected, and separate clean ERC/DRC
results. It does not treat an Eeschema process that merely stays alive as proof of schematic IPC.

PowerShell convenience wrapper:

```powershell
.\tools\kicad-docker.ps1 build
.\tools\kicad-docker.ps1 test
.\tools\kicad-docker.ps1 validate tests/fixtures/kicad-project/minimal --erc --drc
```
