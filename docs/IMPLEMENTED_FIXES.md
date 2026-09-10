# Implemented KiCad Automation Fixes

Last updated: 2026-09-10

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
  write-mode promise; `pcb_route_trace` remains available alongside the verified M4 regression.

Verification: the full Docker integration passed against the minimal fixture with both live PCB
and file-backed schematic tools in one server session, followed by clean ERC and DRC.

### Layer-name normalization

- The pinned MCP compatibility layer accepts KiCad display names (`F.Cu`), canonical tool names
  (`F_Cu`), and protobuf/IPC enum names (`BL_F_Cu`) at routing layer boundaries.
- The same normalization covers the supported copper, silkscreen, mask, fabrication, courtyard,
  edge, drawing, comments, and user layers.

Verification: the image build checks representative dotted, canonical, and IPC enum aliases after
applying the version-pinned patch.

### Shared mutation, routing and placement contracts

- `scripts/kicad_contracts.py` provides a stable superset catalog with explicit backend and
  availability metadata, typed `success`/`partial`/`failure` operation envelopes, dirty/saved/
  `document_revision` state, stale-revision rejection, deterministic inspection UUIDs, qualified
  footprint-ID preservation, selective DRC exclusion previews, board hole-floor classification,
  pin-addressed no-connect resolution, ratsnest fallback data, precise schematic-builder schemas,
  and unambiguous project destination paths.
- `scripts/kicad_topology.py` provides obstacle-aware grid routing with Edge.Cuts bounds, pads,
  keepouts, existing copper, layers, clearance, dry-run plans, structured blocking objects and
  atomic live-adapter rollback.
- `scripts/kicad_placement.py` derives hard placement bounds from Edge.Cuts and enforces courtyard
  overlap, connector-edge, antenna-keepout and locked-part constraints without mutating an
  unsatisfiable board.
- `tests/fixtures/placement-intent/placement_intent.json` provides deterministic connector/RF
  intent, edge, antenna, and locked-part data for the placement contract regressions.
- `scripts/kicad_schematic.py` validates complete nested requests before mutation and resolves
  canonical component pins (including USB shield names such as `SH`).
- `preserve_footprint_ids` reports library-qualified schematic/PCB footprint parity and stable
  mismatch UUIDs so synchronization cannot silently drop a library prefix.
- `scripts/kicad_promotion.py` computes a reviewed copper delta and supplies stale-source checks,
  save/re-read validation and IPC rollback hooks. Automatic promotion remains opt-in.
- `scripts/kicad_live_adapter.py` adds named-pin no-connect resolution, ERC delta reporting,
  revision-aware stale rejection, KiCad 10 ratsnest fallback metadata, selective DRC previews,
  and fail-closed handling for upstream domain refusals.
- `scripts/kicad_live_promotion.py` binds reviewed copper deltas to the supported live IPC track,
  save, reload, readback, and validation calls. `tests/integration_live_promotion.py` covers the
  successful pinned-runtime path on a disposable board.
- `scripts/kicad_live_placement.py` binds reviewed footprint position deltas to live
  `pcb_move_footprint`, save, reload, readback, and explicit position restoration callbacks.
  `tests/integration_live_placement.py` covers the successful pinned-runtime path; unit coverage
  injects a post-save validation failure and verifies rollback to the saved source.

Verification: `tests/test_design_contracts.py` covers stale writes, postcondition rollback,
blocking-object dry runs, constrained placement success/failure, named-pin no-connects, nested
schema rejection, selective exclusions, board-hole classification, truthful delete failures and
stable route-pad schema handling. The earlier baseline suite passed with 44 tests; the current
suite and new live-adapter regressions are recorded below.

## Partially shipped

### KiCadRoutingTools candidate backend (M6)

- Optional `compose.routing.yaml` builds upstream revision
  `529f873d4c4c20493b1fa786cc9b42ce6cce2945`, including the Rust engine from source.
- `tools/kicad-routing.cmd` / `.ps1` support build, doctor, run and stdio MCP.
- `routing_tools_info`, `routing_run_candidate` and `routing_job_result` provide typed plans
  and persisted results without changing the main MCP Pro profile.
- Source is read-only; staged inputs protect the baseline from upstream input-side edits.
  Original project, schematic and custom-rule files are restored before each independent check.
- Baseline and each routing stage get ERC and DRC with schematic parity. Finding comparison
  rejects new nonconnectivity findings and increased unconnected counts. Hash checks detect
  changed source boards, schematics, projects and custom rules.
- Jobs preserve normalized plans, commands, logs, hashes, full findings and candidate projects.
  No automatic source overwrite or live-board import is implemented.

Detailed implementation, commands and the sequenced remaining plan are in
[`KICAD_ROUTING_TOOLS.md`](KICAD_ROUTING_TOOLS.md). Generic routing has real copper-creation
coverage; differential and plane dispatch now have deterministic electrical fixture coverage.

### KiCad 10 pad lookup for pad-to-pad routing

- The image applies `docker/patches/kicad-mcp-pro-3.34.0-kicad10-pad-lookup.patch` only to the
  pinned upstream version.
- Pad lookup now walks `FootprintInstance.definition.pads`, the supported KiCad 10 `kipy` model,
  instead of reading the nonexistent `Pad.parent` property.
- The image build executes `docker/tests/verify_kicad_mcp_compat.py` after patching, so dependency
  drift or a failed patch stops the build.

`scripts/pad_to_pad_regression.py` now resolves two named pads through `pcb_get_pads`, derives the
advertised `route_from_pad_to_pad` schema, creates copper with the patched KiCad 10 lookup, saves,
reads the live board back, checks the created track's net and runs the pinned Docker validator.

Verification: with `KICAD_MCP_OPERATING_MODE=experimental` on an isolated port, KiCad 10.0.4
created the J1.1-to-J2.1 SIGNAL route, saved it, read back two live-gui tracks, and DRC reported
zero `unconnected_items`. The only remaining DRC findings were the fixture's two pre-existing
`footprint_symbol_mismatch` warnings. The source fixture was copied to a disposable directory and
was not modified.

### Qualified schematic-to-PCB footprint IDs

- `docker/patches/kicad-mcp-pro-3.34.0-qualified-footprint.patch` is scoped to the pinned
  kicad-mcp-pro 3.34.0 renderer and preserves the schematic `Library:Footprint` identity in the
  board footprint root.
- `docker/tests/verify_kicad_mcp_compat.py` renders a qualified fixture and fails if the library
  prefix is dropped. The Docker image applies the patch with `--fuzz=0` and runs that regression.

## Still open

- Upstream does not yet expose `{reference, pin}` directly or a live document revision field;
  `scripts/kicad_live_adapter.py` supplies the supported resolution boundary, explicit mm contract,
  ERC delta, and digest-based stale rejection. The pinned USB-C `J1.SH` path was live-tested.
  Because the pinned surface has no independent schematic-save operation, the live adapter now
  reports `dirty=true, saved=false` unless a verified save callback is supplied; it never claims
  durability from the no-connect mutation alone.
- Precise nested builder schemas and adapter save/revision semantics are implemented and covered;
  the upstream builder remains a file-backed tool with no independent schematic-save operation.
- Complete live connector/module intent fixtures and live rotation/UUID parity remain open; the
  pinned disposable position-promotion path is verified.
- KiCad 10 ratsnest fallback consumption by the upstream tool; the live adapter now consumes
  `get_unconnected_nets` plus DRC and returns `fallback=true`, source, endpoints, and limitations.
- Selective DRC preview, stable native/derived UUID provenance, and project path semantics are
  implemented. The pinned upstream exclusion writer remains unsafe/all-violations-only, so live
  execution fails closed until its schema is corrected upstream.
- Saved-source rollback for a promoted copper delta remains open because the pinned live surface
  lacks a safe exact-track identity/restore primitive. Successful live routing and placement
  promotion/reopen are covered by `tests/integration_live_promotion.py` and
  `tests/integration_live_placement.py`; injected failure and atomic rollback are covered by the
  repository transaction tests.

## Current verification baseline

- Python unit/contract suite: 73 tests passing, including candidate-routing, electrical controls,
  live-adapter, and transactional routing/placement regressions.
- Container build: `local/kicad-automation:10.0.4-mcp-pro` builds with the compatibility test.
- Fixture validation: ERC clean, DRC clean, detailed reports persisted under
  `.kicad-automation/reports/`.

Routing integration: real stdio MCP and Rust generic routing passed on `krt-smoke`; the new
differential fixture reduced unconnected count 4 -> 2 and the plane fixture preserved the
baseline count while creating a GND zone. Both remain `needs_review` because unrelated nets are
intentionally unrouted. The disposable live-promotion regression returned saved/readback success;
the post-mutation validator reported ERC 0 and only expected remaining fixture DRC findings. The
disposable live-placement regression moved J1, saved it, reopened it through IPC, and a service
restart read back the promoted position; its validator likewise reported ERC 0 and the fixture's
expected unconnected/mismatch DRC findings.

## Latest implementation checkpoint

The current working tree additionally hardens the shared contracts: collection-order-independent
semantic board digests; detection of same-UUID copper edits; full track/via geometry readback;
rollback attempts that begin before an apply callback; explicit partial/recovery-required status
when restoration cannot be verified; preflight rejection of unsupported live via/removal deltas;
rotation/layer-preserving placement deltas; Edge.Cuts polygon/cutout checks; strict DRC selector
AND semantics and report-bound previews; structured KiCad 10 track/via parsing; and schema-v2
routing policy validation with credential-free parser capability probes and per-stage regression
gates. The default Codex configuration now includes the optional candidate-routing MCP catalog,
including `routing_plan_trace`.

Verification run in this checkout: `python -m unittest discover -s tests -p 'test_*.py'` (73
passing), `python -m compileall -q scripts tests` (pass), and `git diff --check` (pass). The
pinned images built successfully. `tests/integration_routing_mcp.py` and
`tests/integration_electrical_routing.py` passed in the routing image; isolated KiCad 10.0.4
live routing and placement promotions passed on disposable copies, including placement readback
after service restart. The disposable validation command returned ERC 0 and expected DRC
violations (four intentionally unrouted fixture nets plus two known mismatch warnings), so that
command is a design-result failure rather than an environment failure. Saved-source copper
rollback remains blocked by the upstream KiCad 10 exact-track restore limitation.

Exact runtime commands included `docker compose --project-directory . -f compose.yaml build kicad`,
`docker compose --project-directory . -f compose.routing.yaml build routing`,
`docker compose --project-directory . -f compose.routing.yaml run --rm -T --no-deps routing doctor`,
and the two routing-image integration commands documented in the routing guide. The live checks
used separate Compose projects on ports 3335/3336 with copied `krt-diff`/`krt-smoke` fixtures; the
user's ESP32 service on port 3334 was not stopped, repointed or mutated.
