# Implemented KiCad Automation Fixes

Last updated: 2026-09-09

This document is the delivery record for the problem backlog in [`fixes.md`](../fixes.md). It
separates shipped behavior from work that has only been diagnosed or partially implemented.

## Shipped

### Supported MCP command client

- `scripts/kicad_mcp_client.py` provides `initialize`, `wait`, `list`, `schema`, `call`, and `raw`.
- It supports normal JSON and Streamable HTTP event-stream responses.
- It reads `KICAD_MCP_URL` and `KICAD_MCP_AUTH_TOKEN`, accepts inline JSON or `@file` payloads,
  normalizes HTTP, JSON-RPC, socket-reset, and tool errors, and returns stable exit codes.
- `tools/kicad-mcp.ps1` is the Windows-facing entry point.
- `tools/kicad-docker.ps1 start` delegates readiness checks to the client; it no longer contains
  its own local HTTP request implementation.

Verification: isolated HTTP-server tests cover authorization, request shape, JSON, SSE, schema
lookup, JSON-RPC errors, invalid arguments, and transient socket failures. Live checks against
`kicad-mcp-pro` 3.34.0 confirmed initialization, discovery, schema lookup, server information,
project information, and PCB summary calls.

### Persistent, summarized ERC/DRC reports

- `validate-kicad` now defaults to `/workspace/.kicad-automation/reports`, which is the host bind
  mount, instead of the ephemeral `/runtime/reports` volume.
- Results include `workspace_relative_report_dir` for direct host resolution.
- Every ERC/DRC result includes total findings, counts by severity and type, affected references,
  and up to ten structured findings with UUIDs and coordinates.
- `.kicad-automation/` and generated `*.kicad_prl` files are ignored by Git.

Verification: the pinned KiCad 10.0.4 image was rebuilt and the complete minimal fixture produced
clean ERC and DRC results. The JSON reports and CLI log remained available on the host after the
one-shot container exited.

### Windows execution-policy launchers

- `tools/kicad-docker.cmd` and `tools/kicad-mcp.cmd` apply `-ExecutionPolicy Bypass` only to the
  checked-in wrapper process.
- Users do not need to weaken machine-wide or account-wide PowerShell policy.

Verification: architecture tests assert the scoped invocation, delegated script, and argument
forwarding for both launchers.

### Stable project-building tool surface

- The runtime and Compose default to the upstream `builder` profile with explicit file-backed
  schematic mode, while PCB operations continue to use live KiCad IPC.
- The Codex allowlist includes project creation, schematic construction and inspection,
  schematic-to-PCB synchronization, PCB inspection and editing, supported trace routing, save,
  ERC, DRC, and unconnected-net inspection.
- The Docker integration test asserts the required workflow tools are present whenever the
  builder profile is selected, preventing silent catalog shrinkage during dependency upgrades.
- The experimental `route_from_pad_to_pad` helper is intentionally not part of the stable
  write-mode promise; `pcb_route_trace` remains available while M4 is open.

Verification: the full Docker integration passed against the minimal fixture with both live PCB
and file-backed schematic tools in one server session, followed by clean ERC and DRC.

### Layer-name normalization

- The pinned MCP compatibility layer accepts KiCad display names (`F.Cu`), canonical tool names
  (`F_Cu`), and protobuf/IPC enum names (`BL_F_Cu`) at routing layer boundaries.
- The same normalization covers the supported copper, silkscreen, mask, fabrication, courtyard,
  edge, drawing, comments, and user layers.

Verification: the image build checks representative dotted, canonical, and IPC enum aliases after
applying the version-pinned patch.

## Partially shipped

### KiCad 10 pad lookup for pad-to-pad routing

- The image applies `docker/patches/kicad-mcp-pro-3.34.0-kicad10-pad-lookup.patch` only to the
  pinned upstream version.
- Pad lookup now walks `FootprintInstance.definition.pads`, the supported KiCad 10 `kipy` model,
  instead of reading the nonexistent `Pad.parent` property.
- The image build executes `docker/tests/verify_kicad_mcp_compat.py` after patching, so dependency
  drift or a failed patch stops the build.

Remaining before this is complete: run route creation, save, and DRC on a disposable two-pad
fixture. The upstream tool is currently exposed only in experimental operating mode, so the
normal write-mode service cannot run that integration safely yet.

## Still open

- Pin-addressed schematic no-connect placement and corrected ERC coordinate units.
- Precise nested schematic-builder schemas.
- Explicit save/revision/transaction semantics for mutations.
- Constraint-aware auto-placement.
- Consistent partial-success operation envelopes.
- KiCad 10 ratsnest fallback.
- Selective DRC exclusions, stable inspection UUIDs, and project path semantics.
- Transactional, obstacle-aware routing and rollback.

## Current verification baseline

- Python unit/contract suite: 22 tests passing for the current compatibility baseline.
- Container build: `local/kicad-automation:10.0.4-mcp-pro` builds with the compatibility test.
- Fixture validation: ERC clean, DRC clean, detailed reports persisted under
  `.kicad-automation/reports/`.
