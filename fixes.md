# KiCad Automation Fixes

This backlog records gaps observed while building the ESP32 development board with the
Dockerized KiCad 10 MCP runtime. The priority is to make the supported path deterministic and
agent-friendly: one discoverable tool surface, structured results, persistent diagnostics, and
no need for ad-hoc host-side KiCad or HTTP calls.

Implemented work and verification evidence are tracked in
[`docs/IMPLEMENTED_FIXES.md`](docs/IMPLEMENTED_FIXES.md).

The ordered implementation plan for the remaining acceptance gaps is maintained in
[`docs/REMAINING_FIXES_PLAN.md`](docs/REMAINING_FIXES_PLAN.md). Completed items should be moved
to `docs/IMPLEMENTED_FIXES.md` only after their acceptance checks have been rerun; `fixes.md`
will then remain the active backlog rather than a second historical ledger.

## Acceptance inventory

The stable IDs below split the original acceptance criteria into independently verifiable
work. `VERIFIED` means the recorded evidence meets the live/runtime contract; `PARTIAL` means
the repository boundary is implemented but a required upstream/live capability is still open;
`BLOCKED` means the pinned runtime cannot provide the required safe operation and the adapter
fails closed.

| ID | Status | Scope | Implementation/evidence |
| --- | --- | --- | --- |
| P0-TOOLS-01 | PARTIAL | One-session live + routing discovery | `scripts/kicad_contracts.py`, `.codex/config.toml`; routing remains a separate unavailable backend until a coordinator is connected. |
| P0-TOOLS-02 | VERIFIED | Supported MCP client and SSE/JSON calls | `scripts/kicad_mcp_client.py`, `tests/test_mcp_client.py`. |
| P0-ROUTE-01 | VERIFIED | KiCad 10 named-pad routing | M4 evidence in `docs/IMPLEMENTED_FIXES.md`; preserved this pass. |
| P0-TOPO-01 | PARTIAL | Topology-aware dry run and atomic routing | `scripts/kicad_topology.py`, `tests/test_design_contracts.py`; live promotion rollback after save remains open. |
| P0-REPORT-01 | VERIFIED | Persistent ERC/DRC artifacts | Docker validation/report fixtures and routing integration tests. |
| P1-SCH-01 | PARTIAL | Pin-addressed no-connect and ERC units | `scripts/kicad_live_adapter.py`; pinned surface has no verified schematic-save callback. |
| P1-SCHEMA-01 | PARTIAL | Precise nested builder contracts | `scripts/kicad_contracts.py`, `scripts/kicad_schematic.py`; live upstream builder remains file-backed. |
| P1-STATE-01 | PARTIAL | Save/revision/stale-write semantics | Digest/stale rejection is implemented; durable upstream revision/save endpoint is absent. |
| P1-PLACE-01 | PARTIAL | Constraint-aware placement | `scripts/kicad_placement.py`, `scripts/kicad_live_placement.py`; live rotation/UUID parity remains limited by inspection payload. |
| P1-KRT-PLACE-02 | PARTIAL | KiCadRoutingTools pre-route placement refinement | Typed optimize/reseat stages, exact `move_refs`, and reviewed optimize-candidate promotion are verified; real-board intent acceptance and live reseat coverage remain open. |
| P1-STATUS-01 | VERIFIED | Truthful structured operation status | `OperationResult`, live adapters, and transaction regressions. |
| P1-RATS-01 | PARTIAL | KiCad 10 ratsnest fallback | `McpLiveAdapter.ratsnest()` consumes DRC/unconnected-net fallback; native endpoint remains unavailable. |
| P2-EXCLUDE-01 | BLOCKED | Selective persisted DRC exclusions | Preview/selector contract is implemented; pinned writer is unsafe all-violations-only. |
| P2-UUID-01 | PARTIAL | Stable native UUID exposure | Native IDs are preserved and truncated IDs are marked non-deletion-safe; complete live object pagination is not exposed. |
| P2-PATH-01 | VERIFIED | Project destination/path semantics | `resolve_project_paths()` and Windows/relative path regressions in `tests/test_design_contracts.py`. |
| P2-FOOTPRINT-01 | VERIFIED | Qualified footprint identity preservation | Version-scoped 3.34.0 patch and build-time compatibility regression. |
| P2-API-01 | VERIFIED | Layer/status/result contract quality | Layer normalization, structured status envelopes, and refusal regressions in adapter/contract tests. |
| M6-TRANSACTION-01 | PARTIAL | Live routing/placement promotion and rollback | Disposable live success/readback passes; saved-source copper rollback and coordinator remain open. |

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

**Current evidence:** `scripts/kicad_live_adapter.py` resolves `reference/pin` through live
symbol and pin-position inspection, sends exact millimetre coordinates with snapping off, and
reports the ERC finding delta. A disposable KiCad 10.0.4 USB-C fixture cleared only the `SH`
finding and retained the other pin-not-connected findings after service restart.
The adapter reports `saved=false, dirty=true` unless a verified schematic-save callback is
supplied, because the pinned upstream surface has no independent schematic-save operation;
durability remains open.

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

**Current evidence:** `scripts/kicad_placement.py` derives bounds from Edge.Cuts, checks body and
courtyard overlap, locked parts, connector edges, and antenna keepouts before mutation. The
repository contract covers successful constrained placement and unsatisfiable atomic failure.
`scripts/kicad_live_placement.py` promotes a reviewed position delta through the pinned
`pcb_move_footprint`/save/reopen path; a disposable KiCad 10 fixture verified saved readback.
The live adapter is position-oriented because the pinned footprint listing does not expose a
full rotation/UUID payload; repository constraints still retain the complete intent model.

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
  reference with mandatory dry-run preview for bulk exclusions. The live adapter previews the
  pinned KiCad 10 DRC report and fails closed rather than invoking the upstream tool's unsafe
  all-violation writer; selected live execution remains blocked by that upstream schema.
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
- **Implemented:** live no-connect and ratsnest adapters expose truthful revision/save fields,
  explicit fallback source/limitations, and domain refusal status instead of treating
  `isError=false` refusal text as success.

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
  contracts are implemented and unit-tested. A disposable pinned KiCad 10 live promotion now
  covers candidate application, save, `pcb_revert` reopen, readback, net identity, and structured
  success; live constrained-placement promotion now also covers save/reopen/readback. Shared
  transactions now detect same-UUID edits, preflight unsupported vias/removals before the first
  live write, verify full track/via geometry, preserve placement rotation/layer, and report
  partial/recovery-required status when rollback cannot be verified. Saved-source rollback for a
  copper delta remains open because the pinned live surface does not expose a safe exact-track
  identity/restore primitive.

  **Current KiCadRoutingTools placement/routing state:** candidate plans now run the pinned
  `place_optimize.py` before `planes`/`diff`/`route`, with conservative defaults and per-stage
  ERC/DRC. `move_refs` is an exact allowlist implemented by locking every other parsed footprint;
  `mode: reseat` dispatches to `place_seed.py --reseat ... --evict-depth 0` and requires intent.
  The real isolated smoke moved only J1, kept J2 fixed, routed SIGNAL, reduced unconnected items
  from one to zero, preserved the source hash, and retained only the fixture's two known footprint
  warnings. The routing MCP schema/capability integration also passes.

  **Still missing:** the routing service remains candidate-only and cannot promote placement plus
  copper through one connected MCP transaction; saved-source copper rollback is still unsafe on
  the pinned live API; a representative real board with reviewed connector/RF intent has not yet
  exercised `mode: reseat`; placement `JSON_SUMMARY` quality metrics are not yet parsed into
  `result.json`; and upstream has no public `place_optimize --move-refs` flag, so optimize scoping
  currently uses the behaviorally equivalent, validated lock complement.
  See
  [remaining-fixes implementation plan](docs/REMAINING_FIXES_PLAN.md) and the
  [routing architecture guide](docs/KICAD_ROUTING_TOOLS.md).

Items requiring changes inside `kicad-mcp-pro` should be fixed upstream where possible. Any local
compatibility patch must be pinned to the affected upstream version, covered by a failing-then-
passing integration test, and removed when the pinned dependency contains the fix.

M4 is complete for the pinned runtime: the version-pinned KiCad 10 pad lookup patch, build-time
regression, and `scripts/pad_to_pad_regression.py` are in place. In an isolated experimental-mode
KiCad 10.0.4 service, J1.1-to-J2.1 was resolved and routed on SIGNAL, saved, read back as live
tracks, and checked by DRC with zero unconnected items. The fixture's two pre-existing
`footprint_symbol_mismatch` warnings remain documented; they are not hidden by the regression.

The qualified-footprint synchronization defect is now patched narrowly for kicad-mcp-pro 3.34.0:
the file-backed renderer preserves the schematic `Library:Footprint` name in the board footprint
root. The image build regression exercises that renderer before the service starts.
