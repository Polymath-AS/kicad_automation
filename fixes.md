# KiCad Automation Fixes

This backlog records gaps observed while building the ESP32 development board with the
Dockerized KiCad 10 MCP runtime. The priority is to make the supported path deterministic and
agent-friendly: one discoverable tool surface, structured results, persistent diagnostics, and
no need for ad-hoc host-side KiCad or HTTP calls.

Implemented work and verification evidence are tracked in
[`docs/IMPLEMENTED_FIXES.md`](docs/IMPLEMENTED_FIXES.md).

## P0 — Blocks reliable board generation

### Provide one stable, complete MCP tool surface

**Observed:** The default `pcb_only` profile exposes only a small PCB catalog. Schematic creation,
pad inspection, routing helpers, and validation require changing profiles, restarting the service,
and restarting Codex so its cached catalog refreshes.

**Fix:** Expose a stable superset of supported tools. Each tool should report its backend and
availability (`live_ipc`, `file_backed`, `cli`, or `unavailable`) instead of disappearing between
profiles. Keep write permissions separate from discoverability.

**Acceptance:** One session can create/sync a schematic, inspect and edit the PCB, save, and run
ERC/DRC without changing `KICAD_MCP_PROFILE` or reconnecting the client.

### Integrate raw MCP calls into the repository toolset

**Observed:** Tools hidden by the active client catalog had to be called with hand-written
`Invoke-WebRequest` JSON-RPC payloads, headers, URLs, and development tokens.

**Fix:** Add a supported repository CLI for MCP initialization, readiness checks, discovery,
schema inspection, and tool calls. It must parse both JSON and Streamable HTTP SSE responses,
read connection settings from environment variables, and return useful exit codes.

**Acceptance:** No workflow documentation or automation contains a hand-written local HTTP MCP
request. Calls are reproducible through the checked-in CLI and testable without KiCad.

### Make pad-to-pad routing work on KiCad 10

**Observed:** `route_from_pad_to_pad` failed consistently with
`'Pad' object has no attribute 'parent'`. Routing then required fetching pad coordinates and
calling the lower-level straight-segment primitive manually.

**Fix:** Resolve a pad's footprint through the supported KiCad 10 IPC API, normalize pad/net
identity, and add regression coverage using the pinned runtime.

**Acceptance:** A route between two named pads is created, assigned to the correct net, saved,
and verified by DRC in the KiCad 10.0.4 container.

### Add topology-aware routing with atomic failure

**Observed:** `pcb_route_trace` accepts coordinates but does not plan around pads, footprints,
keepouts, board edges, or existing copper. It can create crossings and shorts one segment at a
time, leaving partial work behind.

**Fix:** Add pad-aware path planning with configurable doglegs, layers, vias, clearance checks,
dry-run preview, and rollback when postconditions fail.

**Acceptance:** Routing either commits a DRC-safe path or leaves the board unchanged and returns
structured blocking objects and coordinates.

### Persist and return detailed ERC/DRC artifacts

**Observed:** Docker validation wrote JSON and logs under the ephemeral `/runtime` volume. Detailed
diagnosis required invoking the host KiCad installation and copying reports manually.

**Fix:** Default reports to the bind-mounted workspace, return host-resolvable paths, and include
a concise category/reference summary in the command result.

**Acceptance:** `kicad-docker.ps1 validate ... --erc --drc` leaves ERC JSON, DRC JSON, and the CLI
log under `.kicad-automation/reports/` after the container exits.

## P1 — Causes incorrect edits or misleading results

### Add no-connect markers by component pin

**Observed:** `sch_add_no_connect` accepts only coordinates. ERC coordinates claimed millimetres
but were scaled by 1/100 relative to schematic coordinates, so direct use placed markers far from
their pins. USB-C shield pin naming also differed (`SH`, not `S1`).

**Fix:** Support `{reference, pin}` as the preferred input, resolving the terminal internally.
Correct the ERC coordinate unit/scale contract and expose canonical pin names from symbol data.

**Acceptance:** Adding a no-connect to `J1.SH` clears only that ERC finding without coordinate
math or file inspection.

### Make schematic builder schemas match implementation

**Observed:** `sch_build_circuit` examples/documentation used `lib_id`, while runtime validation
required `library` and `symbol_name`. Generic nested schemas hid required child properties until a
call failed.

**Fix:** Publish precise JSON schemas for nested models and accept one canonical symbol identifier
consistently across schematic tools. Validate the whole request before mutating the design.

**Acceptance:** Tool discovery alone is sufficient to construct a valid request; documentation
examples pass contract tests.

### Define save, reload, and synchronization semantics

**Observed:** Successful outline and schematic synchronization operations were not always durable
until an explicit `pcb_save`; changing backends/reloading could discard apparently successful
work.

**Fix:** Every mutation result must state `dirty`, `saved`, and `document_revision`. Sync commands
must reject stale revisions, and multi-step operations should offer `save=true` or a transaction.

**Acceptance:** A reported saved mutation survives service restart, and stale-document writes fail
before modification.

### Correct automatic placement constraints

**Observed:** schematic-to-PCB synchronization used a placement frame inconsistent with the board
outline, placed parts outside the board, overlapped footprints, and ignored connector edge and
module antenna requirements.

**Fix:** Derive the placement region from `Edge.Cuts`; add hard constraints for inside-board,
overlap, courtyard, connector edge, antenna keepout, and locked parts.

**Acceptance:** Auto-placement produces zero hard-constraint violations or returns a non-mutating
failure identifying unsatisfied constraints.

### Return trustworthy operation status

**Observed:** `pcb_delete_items` could delete objects but report postcondition verification failure
while also returning `isError: false`.

**Fix:** Standardize results as `success`, `partial`, or `failure`, include verified effects, and
never combine contradictory transport and domain status.

**Acceptance:** Clients can decide retry/rollback behavior from structured fields without parsing
message text.

Additional routing-fixture evidence: `pcb_sync_from_schematic` can refuse a write while returning
`isError: false`; the fixture helper checks that refusal explicitly. Synchronization also left
two footprint IDs without their library prefix, producing `footprint_symbol_mismatch` warnings.
Preserve qualified footprint IDs during transfer and add a parity regression fixture. Neither
defect is fixed by the candidate router; its validator preserves and reports these warnings.

### Provide supported KiCad 10 ratsnest fallback

**Observed:** `pcb_get_ratsnest` reports that the live ratsnest API is unavailable in KiCad 10 even
though unconnected-net and DRC information can provide a supported fallback.

**Fix:** Return a documented fallback from `get_unconnected_nets()` and/or DRC, marked with its
source and limitations.

**Acceptance:** The tool returns actionable unconnected endpoints on the pinned KiCad version.

## P2 — Workflow and API quality

- **Implemented:** normalize layer inputs (`F.Cu`, `F_Cu`, and `BL_F_Cu` IPC enum forms) and
  provide contract coverage for stable inspection UUIDs, typed mutation envelopes, and the
  supported backend boundaries. Upstream tool-specific additions still require live coverage.
- **Implemented in the repository adapter:** include stable UUIDs in shape, track, pad, and
  violation inspection results so exact deletion and exclusion are possible.
- **Implemented in the repository adapter:** selective DRC filters by UUID, rule, type, and
  reference with mandatory dry-run preview for bulk exclusions; live upstream exclusion wiring
  remains to be exercised.
- **Implemented in the repository adapter:** board-level minimum through-hole and NPTH constraints
  distinguish footprint-internal library exceptions from real board-rule violations.
- **Implemented in the repository adapter:** `sch_analyze_net_compilation` defaults to the current
  schematic when a current-document resolver is supplied.
- **Implemented in the stable catalog:** ERC tools are discoverable alongside schematic mutation
  tools rather than tied to a profile.
- **Implemented in the repository adapter:** project destination resolution returns all created
  paths without implicit nested duplication.
- **Implemented:** avoid Windows execution-policy friction with scoped `.cmd` launchers. Docker
  permission failures are classified and preserved, while host privilege policy remains external.

## Implementation milestones

- [x] **M1:** Check in this evidence-based backlog.
- [x] **M2:** Add and test the repository MCP client; replace new ad-hoc HTTP usage in docs/scripts.
- [x] **M3:** Persist validation artifacts under the mounted workspace and test the path contract.
- [x] **M4:** Add an integration regression for KiCad 10 pad-to-pad routing and fix upstream or carry
  a narrowly versioned compatibility patch.
- [x] **M5:** Deliver the stable catalog/backend metadata and eliminate profile switching for the
  end-to-end board workflow.
- [ ] **M6:** Add transactional topology-aware routing and constraint-aware placement.
  **Partially implemented:** pinned KiCadRoutingTools candidate backend, typed CLI/MCP plans,
  isolated source copies, per-stage ERC/DRC, original-rule restoration and regression detection.
  Repository-level transactional routing, dry-run blockers, rollback and constrained placement
  contracts are now implemented and unit-tested; live IPC promotion/reopen coverage remains open.
  See
  [R1-R6 and detailed execution steps](docs/KICAD_ROUTING_TOOLS.md).

Items requiring changes inside `kicad-mcp-pro` should be fixed upstream where possible. Any local
compatibility patch must be pinned to the affected upstream version, covered by a failing-then-
passing integration test, and removed when the pinned dependency contains the fix.

M4 is complete for the pinned runtime: the version-pinned KiCad 10 pad lookup patch, build-time
regression, and `scripts/pad_to_pad_regression.py` are in place. In an isolated experimental-mode
KiCad 10.0.4 service, J1.1-to-J2.1 was resolved and routed on SIGNAL, saved, read back as live
tracks, and checked by DRC with zero unconnected items. The fixture's two pre-existing
`footprint_symbol_mismatch` warnings remain documented; they are not hidden by the regression.
