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

## Quick Start

After cloning, start the KiCad container and Codex together:

```powershell
.\tools\kicad-docker.ps1 start
```

The first run builds the Docker image, waits for the MCP endpoint, and then opens Codex. No token
setup is required. Docker Desktop must be installed and running.

Running plain `codex` is also safe: the KiCad MCP server is optional during Codex startup, so an
unavailable container no longer prevents the session from opening. Start the container and open a
new Codex session when you need KiCad tools.

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

Codex reads the project-scoped `.codex/config.toml` only for a trusted project. Its static
Authorization header matches the non-secret development token used by Compose. The service is
published only on host loopback, and a missing service does not prevent Codex from starting.
Verify the connection with `codex mcp list` and the `/mcp` command in the Codex interface.

For automation, diagnostics, and tools that are not visible in a client's cached catalog, use the
checked-in MCP client instead of constructing HTTP requests by hand:

```powershell
.\tools\kicad-mcp.ps1 wait
.\tools\kicad-mcp.ps1 list
.\tools\kicad-mcp.ps1 schema pcb_get_board_summary
.\tools\kicad-mcp.ps1 call pcb_get_board_summary --arguments '{}'
```

`list` annotates the live response with stable backend/availability metadata. Use
`.\tools\kicad-mcp.ps1 catalog` for the complete discoverable superset, including tools that are
currently unavailable in a selected upstream operating mode. Discoverability does not grant write
permission.

`--arguments` also accepts `@path/to/arguments.json`, which avoids shell-quoting problems for
larger payloads. Connection settings can be overridden with `KICAD_MCP_URL` and
`KICAD_MCP_AUTH_TOKEN`.

Codex project config example:

```toml
[mcp_servers.kicad]
url = "http://127.0.0.1:3334/mcp"
http_headers = { Authorization = "Bearer kicad-automation-local-dev-token-change-me-2026" }
required = false
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

The default profile is `builder` with `KICAD_MCP_OPERATING_MODE=write` and file-backed schematic
support. It exposes the stable project-building surface needed to create and inspect schematics,
synchronize and edit a live PCB, route, save, and run ERC/DRC without restarting the service.
Use `manufacturing` or another specialized upstream profile only for workflows outside that
design surface.

Schematic support is split deliberately:

- KiCad 10.0.4 does not provide a verified schematic-editor IPC surface. The official IPC
  documentation describes KiCad 9/10 IPC as GUI-only and PCB-oriented; the installed `kipy`
  schematic class is marked KiCad 11-only and is incompatible with the bundled KiCad 10
  protobufs. The runtime therefore does not start Eeschema as a false readiness signal.
- The default `builder` profile exposes MCP Pro's supported file-backed schematic tools with
  `KICAD_MCP_SCHEMATIC_MODE=file_backed`. Their responses identify `Source: file-backed`.
- `KICAD_MCP_SCHEMATIC_MODE=live` fails early with the exact unsupported-stack diagnosis. It is
  reserved for a future verified KiCad 11+ IPC configuration; it does not silently fall back to
  file editing.

The project-scoped Codex allowlist includes the supported file-backed schematic inspection tools;
restart Codex after changing the server profile so its tool catalog is refreshed.

The integration test records `liveSchematicContext`, `liveSchematicRead`, schematic tool
exposure, and the backend identified by the schematic read. Set
`KICAD_TEST_SCHEMATIC_LIVE=1` only when testing a stack that is expected to provide a real live
schematic document; the test fails if MCP reports a file-backed fallback.

The pinned KiCad 10 pad-to-pad regression is opt-in because upstream exposes
`route_from_pad_to_pad` only in experimental write mode. Run it against a disposable two-pad
project with `KICAD_MCP_OPERATING_MODE=experimental` and `KICAD_TEST_PAD_TO_PAD=1`;
`scripts/pad_to_pad_regression.py` resolves named pads, routes and saves them, reads the live board
back, checks net assignment, and runs DRC. It reports pre-existing fixture warnings separately
from unconnected-route failures.

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

## Preferred KiCadRoutingTools placement and routing

The separate routing image exposes conservative placement refinement plus `route`, `diff`, and
`planes` as validated candidate jobs through CLI and MCP. After initial MCP placement, save the
unrouted board and use the candidate placer's bounded moves to improve routability. Lock
connectors, mounting parts, and RF/mechanical-critical parts, and provide reviewed placement
intent when available. KiCadRoutingTools is the preferred routing path; direct IPC traces remain
useful for previews and small reviewed fixes. The candidate service reads the source project
through a read-only mount, preserves the original rules for ERC/DRC, and never automatically
overwrites the live board.

```powershell
.\tools\kicad-routing.cmd build
.\tools\kicad-routing.cmd doctor
.\tools\kicad-routing.cmd run routing-plans/smoke.json
```

The smoke fixture is expected to return `needs_review`: routing resolves its missing connection,
but two pre-existing footprint identifier warnings remain. Non-clean candidates return exit 1.
See [the detailed integration guide and remaining milestones](docs/KICAD_ROUTING_TOOLS.md)
for installation, MCP configuration, plans, evidence, review, limitations and tests.

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

On Windows hosts that enforce a restrictive PowerShell execution policy, use the checked-in
launchers instead of changing machine or user policy:

```bat
tools\kicad-docker.cmd start
tools\kicad-docker.cmd validate tests/fixtures/kicad-project/minimal --erc --drc
tools\kicad-mcp.cmd call pcb_get_board_summary
```
