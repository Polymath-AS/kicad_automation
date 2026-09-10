# Remaining KiCad Automation Fixes: Implementation Plan

This document is the execution plan for the acceptance criteria that remain open after commit
`679d370`. It complements, rather than duplicates, the other project documents:

- [`../fixes.md`](../fixes.md) is the active backlog and source of acceptance criteria.
- [`IMPLEMENTED_FIXES.md`](IMPLEMENTED_FIXES.md) is the completion and verification archive.
- [`KICAD_ROUTING_TOOLS.md`](KICAD_ROUTING_TOOLS.md) is the operator and architecture guide.

An item moves out of the active backlog only after its acceptance test has been rerun against the
supported runtime. "Implemented in the repository adapter" is not complete when the acceptance
criterion requires behavior on the live upstream MCP surface.

## Documentation and status model

Assign every fix a stable identifier, such as `P0-TOOLS-01`, `P0-ROUTE-02`, and
`P1-STATUS-01`. Keep only `OPEN`, `PARTIAL`, and `BLOCKED` work in `fixes.md`. Move completed
items into `IMPLEMENTED_FIXES.md` with their original observation, implementation, commit,
runtime version, regression tests, and exact verification evidence.

`KICAD_ROUTING_TOOLS.md` should describe how the routing system works and how to operate it. Its
R1-R6 backlog sections should ultimately be replaced by links to the stable IDs in `fixes.md` so
that remaining work is not described differently in multiple files.

Likely archive candidates, subject to a fresh acceptance run, are M1-M5, the repository MCP
client, persistent ERC/DRC reports, the M4 KiCad 10 pad lookup, layer normalization, Windows
launchers, qualified footprint preservation, project destination semantics, nested schematic
request validation, and pin-addressed no-connect support.

M6, routing discovery, router policy controls, complete saved-source rollback, live placement
rotation/UUID parity, live selective exclusions, upstream ratsnest consumption, exact operation
status, electrical signoff, and runtime hardening remain active.

## Phase 1: make KiCadRoutingTools discoverable in a normal session

The topology-aware backend is currently available through `tools/kicad-routing.cmd` and a
separate stdio MCP server, but it is not present in the ordinary live KiCad tool catalog.

Implementation:

1. Register the routing MCP server in the repository's default client configuration instead of
   leaving registration only in an example.
2. Ensure a fresh client session discovers the live KiCad tools and these routing tools together:
   `routing_tools_info`, `routing_run_candidate`, `routing_plan_trace`, and
   `routing_job_result`.
3. Add backend metadata for `live_ipc`, `routing_candidate`, `transactional_promotion`, and
   `unavailable`; keep discovery independent of permission to mutate.
4. Make the tool descriptions clearly distinguish the topology-aware candidate router from
   `route_from_pad_to_pad` and `pcb_route_trace`.
5. Add an integration test that starts the supported services, initializes both MCP transports,
   checks their schemas, and calls both live inspection and candidate-routing tools without a
   profile change or client reconnect.
6. Remove ordinary workflow instructions that require hand-written HTTP calls or manual
   `tools/call` requests.

Acceptance: one fresh agent session can discover and invoke both live KiCad and
KiCadRoutingTools operations using checked-in configuration.

## Phase 2: expose safe routing and fabrication controls

The pinned upstream router supports controls that the typed repository plan does not expose. In
particular, the current adapter cannot select a hard fabrication tier, disable below-board-floor
rescue, enforce strict sizes, or configure the iteration budget. A router can therefore report
connectivity while producing a candidate that the independent validator must reject.

Extend `RoutingStep`, `validate_plan()`, command construction, MCP schemas, examples, and result
evidence with bounded support for:

- `max_iterations` and `max_probe_iterations`;
- `fab_tier` (`standard`, `advanced`, or `auto`);
- `escalation` (`off`, `board`, or `fab`);
- `strict_sizes` and `no_fix_drc_settings`;
- `force_reroute`, `rip_existing_nets`, and `keep_input_copper`;
- `same_net_pad_clearance`, `routing_clearance_margin`, `hole_to_hole_clearance`, and
  `board_edge_clearance`.

Use a production-safe policy that never silently weakens the saved project. New plans should
normally use `fab_tier=standard`, `escalation=board`, `strict_sizes=true`, and
`no_fix_drc_settings=true`. If compatibility requires retaining legacy defaults, version the
plan schema and label legacy relaxation explicitly rather than changing existing meaning
silently.

Every result must include the iteration budget and actual use, requested and delivered widths,
drills and clearances, every relaxation, whether strict-size enforcement stopped the run, and a
separate router-process status and candidate-acceptance status.

Tests:

- unit tests for every valid/invalid field and generated CLI argument;
- rejection of incompatible operation-specific fields before staging;
- a regression where a 0.127 mm rescue is rejected under a 0.20 mm board floor;
- proof that candidate routing cannot modify the original `.kicad_pro` rules;
- a pinned-runtime candidate that succeeds without size or clearance relaxation.

## Phase 3: stage live projects without stopping KiCad

Replace the save-stop-route-restart sequence with a supported saved-snapshot handoff:

1. Save the live board through IPC.
2. Reopen/read back the saved state and record its document revision.
3. Hash the PCB, schematic, project, custom rules, and project-local libraries.
4. Copy the saved project into `.kicad-automation/staging/<id>/`, excluding editor locks and
   transient state.
5. Verify staged hashes and route the unlocked snapshot, not the live project directory.
6. Re-read the live source revision and hashes before promotion.
7. Reject a stale candidate before any source mutation.

Acceptance: candidate routing can run while the live document remains open, and an independent
edit causes deterministic pre-mutation stale rejection.

## Phase 4: provide complete structured copper identity and mutations

Full promotion and rollback require native object identity. Prefer an upstream-compatible
`kicad-mcp-pro` change. If a local patch is necessary, scope it to 3.34.0 and make the image build
run a failing-without-the-patch regression.

Inspection must return complete structured track and via objects, including native UUID, kind,
geometry, layer set, width/diameter/drill, net identity, and locked state. Mutation tools must
return every created UUID, report per-object effects, support exact UUID deletion, and verify
readback. A domain refusal or failed postcondition must be a structured `failure` or `partial`,
never successful transport with contradictory prose.

Tests:

- UUID stability across repeated inspection, save, reopen, and service restart;
- exact track and via creation/deletion;
- mixed-success batch behavior;
- truthful `status`, `dirty`, `saved`, `document_revision`, and `verified_effects` fields;
- regression for the current ambiguous `pcb_delete_items` postcondition response.

## Phase 5: complete transactional routing promotion and rollback

Build full M6 routing promotion on the structured copper API:

1. Inspect and snapshot the source document.
2. Record source revision and contract hashes.
3. Generate and validate an isolated candidate under the original rules.
4. Calculate a typed track/via delta and reject unexpected schematic, footprint, stackup, or
   rule changes.
5. Recheck revision and hashes.
6. Apply the complete delta as one logical transaction.
7. Run pre-save live validation.
8. Save, reopen, and compare every promoted object and net with the candidate.
9. Run final DRC/ERC checks and return structured success.

On any failure, restore removed objects, remove added objects, save, reopen, compare the restored
document with the original digest, and rerun validation. Refuse copper-removal candidates until
the adapter can serialize and recreate every affected object safely.

Failure injection must cover stale source, mid-batch track failure, via failure, save failure,
reopen failure, readback mismatch, and post-promotion DRC regression. M6 routing is complete only
when failures after mutation and after save both restore the original reopened board.

## Phase 6: complete live constrained-placement promotion

Extend live footprint inspection with full UUID, position, rotation, side, locked state, body
bounds, and courtyard bounds. Promote both translation and rotation through the shared
transaction boundary.

Use explicit project/fixture intent for connector edges and antenna regions rather than reference
name conventions. Add real connector and RF-module fixtures covering Edge.Cuts bounds,
courtyard/body overlap, connector edge, antenna keepout, relevant clearances, and locked parts.

Tests must prove successful save/reopen/restart durability, unsatisfiable non-mutation, and
rollback after a post-save constraint or readback failure.

## Phase 7: finish the remaining live API gaps

### Selective DRC exclusions

Add an upstream or version-scoped live writer that accepts explicit violation UUIDs. Retain the
mandatory dry-run digest and reject stale previews. Test one finding, filtered multiple findings,
zero matches, invalid selectors, stale previews, persistence after reopen, and rollback.

### KiCad 10 ratsnest fallback

Return the adapter fallback through the ordinary `pcb_get_ratsnest` contract, including its
source, limitations, endpoint coordinates, net identity, and native/derived UUID provenance.
Ensure repository callers accept fallback results instead of rejecting non-native data.

### Operation status consistency

Apply the shared `success`/`partial`/`failure` envelope at the real MCP boundary, with `dirty`,
`saved`, `document_revision`, `verified_effects`, `retryable`, and rollback information. Add
contract tests for every upstream refusal pattern encountered during routing and synchronization.

## Phase 8: electrical routing acceptance

Retain the existing differential and plane dispatch fixtures, then add production-oriented
acceptance for stackup-aware impedance, length matching, fanout, plane connectivity, keepouts,
and save/readback durability. Capability boundaries not exposed by the pinned upstream revision
must be explicit in schema and results rather than simulated.

Use a disposable copy of the buck regulator as an end-to-end integration case:

1. Start with zero tracks and a placement with no hard overlap violations.
2. Route under strict board-floor enforcement.
3. Prove no rule relaxation and no below-floor feature occurred.
4. Verify every intended pad group is connected with no shorts or new DRC findings.
5. Promote through live IPC, save, reopen, and compare.
6. Inject a post-save failure and prove complete rollback.

Rejected candidates that connect every pad but violate fabrication floors should remain negative
fixtures; connectivity alone is not acceptance.

## Phase 9: runtime and release hardening

After transactional correctness is complete, add asynchronous job submission, polling,
cancellation, process-group termination, persisted incomplete-job recovery, transitive package
locks, CI evidence artifacts, board-size/resource calibration, and Windows/Linux launcher tests.
Run the complete routing fixture suite before changing the pinned KiCadRoutingTools revision.

## Delivery order and completion gates

Implement in this order:

1. Documentation split and stable fix IDs.
2. Router schema and strict fabrication controls.
3. Default MCP discovery.
4. Lock-free live snapshot staging.
5. Structured track/via UUID APIs and truthful mutation status.
6. Full routing promotion and saved-source rollback.
7. Placement rotation/UUID parity and rollback.
8. Selective exclusions, ratsnest consumption, and remaining result consistency.
9. Buck-regulator and electrical signoff regressions.
10. Async execution and release hardening.

The critical path is phases 2-6. Until those gates pass, KiCadRoutingTools remains a validated
candidate generator rather than a dependable live autorouter, and M6 must remain incomplete.
