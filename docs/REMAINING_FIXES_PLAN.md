# Remaining KiCad Automation Fixes: Implementation Plan

This document is the execution plan for the acceptance criteria that remain open after commit
`679d370`. It complements, rather than duplicates, the other project documents:

- [`../fixes.md`](../fixes.md) is the active backlog and source of acceptance criteria.
- [`IMPLEMENTED_FIXES.md`](IMPLEMENTED_FIXES.md) is the completion and verification archive.
- [`KICAD_ROUTING_TOOLS.md`](KICAD_ROUTING_TOOLS.md) is the operator and architecture guide.

An item moves out of the active backlog only with recorded acceptance evidence from the
supported runtime. Preserve existing M4 evidence; rerun it only if affected code changes or a
regression is suspected. "Implemented in the repository adapter" is not complete when the acceptance
criterion requires behavior on the live upstream MCP surface.

## Documentation and status model

Assign every fix a stable identifier, such as `P0-TOOLS-01`, `P0-ROUTE-02`, and
`P1-STATUS-01`. Keep only `OPEN`, `PARTIAL`, and `BLOCKED` work in `fixes.md`. Move completed
items into `IMPLEMENTED_FIXES.md` with their original observation, implementation, commit,
runtime version, regression tests, and exact verification evidence.

`KICAD_ROUTING_TOOLS.md` should describe how the routing system works and how to operate it. Its
R1-R6 backlog sections should ultimately be replaced by links to the stable IDs in `fixes.md` so
that remaining work is not described differently in multiple files.

Likely archive candidates, subject to checking recorded acceptance evidence and rerunning affected tests, are M1-M5, the repository MCP
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
normally use `fab_tier=standard`, `escalation=off`, `strict_sizes=true`, and
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

1. Check the expected live revision and save through IPC when explicitly requested by the job.
2. Read back the saved state and record its document revision; do not revert the editor during
   staging, because an independent edit could otherwise be discarded.
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
3. Structured track/via UUID APIs, revision protection and truthful mutation status.
4. Shared promotion and saved-source rollback primitives.
5. Live snapshot staging and routing orchestration.
6. Default MCP discovery and end-to-end routing promotion.
7. Placement rotation/UUID parity and rollback.
8. Selective exclusions, ratsnest consumption, and remaining result consistency.
9. Buck-regulator and electrical signoff regressions.
10. Async execution and release hardening.

The critical path includes phases 2-6. Until those gates pass, KiCadRoutingTools remains a validated
candidate generator rather than a dependable live autorouter, and M6 must remain incomplete.

## Implementation instructions for Luna

The work packages below refine the phases above. They specify proposed interfaces, not tools
already available in the runtime. Never call a proposed tool until it is implemented, registered,
and discovered. Implement in dependency order and record each package's evidence separately.
The WP dependency labels below govern implementation order; the phases above group requirements
by subject. Do not postpone independent packages when another package has an external blocker.

### Start and scope

Read `fixes.md`, `IMPLEMENTED_FIXES.md`, this document, `KICAD_ROUTING_TOOLS.md`, root and nested
`AGENTS.md`, README runtime instructions, and the files named by the current package. Inspect
`git status --short` and the current commit before editing. Existing untracked buck/ESP32 projects
and output are user work; integration tests must target disposable copies with independent
service ports and project mounts. Do not commit or push implementation unless separately asked.

Start with the existing unittest suite as a baseline. Reuse existing abstractions and tests, but
replace fixture-specific production logic. Unit success does not establish live IPC compatibility.
Do not close an item because a helper exists while the registered MCP endpoint still bypasses it.

### Review findings that must become regressions

These are code observations at the reviewed baseline, not claims of passing/failing runtime tests:

| Location | Observed implementation | Required regression |
| --- | --- | --- |
| `kicad_promotion.py:TransactionalPromotion.promote` | `mutated=True` is set after `apply` returns | Apply the first object, raise on the second, and verify restoration |
| `kicad_promotion.py:geometry_delta` | Compares UUID membership, missing edits with the same UUID | Change width, endpoints, net, and via drill without changing IDs |
| `kicad_promotion.py:_verify_copper_readback` | Checks existence/net incompletely | Reject wrong geometry, wrong via net/drill, extra copper and missing removals |
| `kicad_live_promotion.py:read_board` | Parses rounded text and assumes no vias | Read multiple pages, sub-0.01 mm geometry, vias, and nets containing spaces |
| `kicad_live_promotion.py:apply_delta` | Rejects vias after adding tracks | Unsupported objects must fail before the first write |
| `kicad_live_promotion.py:restore` | Reloads the latest saved board | Inject failure after save and restore the older source |
| `kicad_live_promotion.py:validate` | Looks for `USB_D_P` in text | Detect a short on any net and reject malformed/missing reports |
| `kicad_live_placement.py` | Parses abbreviated IDs without rotation; defaults rotation to zero | Preserve an initially rotated footprint through move and rollback |
| `kicad_promotion.py:_verify_placement_readback` | Checks positions only | Reject wrong rotation or side after reopen |
| `.codex/routing.example.toml` | Omits `routing_plan_trace` from enabled tools | Configured allowlist matches the intended discovered surface |

Also audit `board_digest` for order sensitivity, placement DRC parsing for repeated nested report
copies, and `summarize_kicad_report.py` for IDs derived from array indices. Add targeted regressions
where those behaviors affect comparisons or precise follow-up operations.

### WP0: acceptance inventory and archive (no dependency)

Create a table in `fixes.md` mapping every original acceptance criterion to a stable ID, status,
implementation path, test, and remaining gap. Split compound items into separately verifiable
subcriteria. Existing M5 evidence covers the builder workflow; add a new discovery criterion for
KiCadRoutingTools rather than silently redefining M5. Keep M4 complete.

Archive only fulfilled subcriteria. Retain original observations and limitations in
`IMPLEMENTED_FIXES.md`. Builder schemas, no-connects, destination semantics, and revisions must
remain active wherever only helper-level coverage exists. Do not require a new commit hash before
archiving uncommitted work: record the baseline and pending commit with exact test evidence.

### WP1: policy/schema/metrics (no dependency)

Edit `scripts/kicad_routing.py`, `tests/test_routing_jobs.py`,
`tests/integration_routing_mcp.py`, routing example plans, and routing documentation.

Introduce `schema_version: 2`; omitted version means legacy v1. Preserve v1 argument behavior but
emit a deprecation/policy warning. New examples explicitly select v2. For v2, default to exact
sizes: `fab_tier=standard`, `escalation=off`, `strict_sizes=true`,
`no_fix_drc_settings=true`. An explicit board-floor exploration policy may use
`escalation=board, strict_sizes=false`; it still cannot be promoted below original rules.
Do not combine strict requested-size success with implicit permission to narrow requested sizes.

Use typed enums and one options table shared by validation and argument generation. Proposed
adapter limits: iterations 1..10,000,000; probe iterations 1..max_iterations; grid 0.025..1 mm;
clearance margin 1..3; board/hole clearances 0..10 mm; same-net pad clearance either -1 or 0..10.
Reject booleans as numbers, nonfinite values, unknown keys, and conflicting `force_reroute` with
`keep_input_copper`. Reuse net-pattern validation for rip-up scope; require explicit scope for
removal. Keep existing timeout/resource limits independent of iteration limits.

Before enabling each option, inspect its parser in the pinned container: route, diff and planes
do not necessarily accept the same flags. Test each allowed operation/option combination.
Never add arbitrary argument passthrough. Use sanitized subprocess environments for help and
capability probes too: upstream prints environment variables, including inherited credentials.

Prefer upstream `--json-out` for route metrics if confirmed supported. Store raw metrics plus a
normalized summary with nullable counters and scope (`main_search`, `rescue`, `whole_job`). Do
not report a main-loop count as total work: observed rescue logs exceeded 400,000 iterations while
the main summary reported approximately 16,000. Missing metrics mean unknown, not zero.

Preserve output/logs on strict-size exit 3 and label it policy rejection, separately from a crash.
Restore contract files even on nonzero exits when a candidate exists. Compare each validated
stage to the baseline and stop on regression; the current final-stage-only comparison must not
let a bad intermediate stage silently proceed. Add source and candidate contract-hash assertions.

### WP2: structured inspection and revision boundary (depends on WP0)

Edit `scripts/kicad_contracts.py`, `scripts/kicad_live_adapter.py`, promotion adapters and tests.
Inspect installed 3.34.0 tool implementations and KiCad 10 IPC item serialization before writing
any patch. Extend the actual upstream result payloads; keep human text as an additive compatibility
field. A local patch belongs in `docker/patches/`, is version checked in `docker/Dockerfile`, and
is exercised by `docker/tests/verify_kicad_mcp_compat.py` and live tests.

Define a shared board snapshot carrying native UUIDs, full geometry, nets, footprints, outline,
zones, rules and locked state. Use integer nanometres internally and millimetres at the API;
normalize angles modulo 360 and layer aliases. Paginate until complete and reject missing pages
or duplicate UUIDs. Truncated UUIDs and derived finding IDs are never valid native delete targets.
Include via diameter/drill/type/layer span and arc geometry. Reject unsupported object kinds
before mutation; publish that limitation in capabilities.

Use two digests: an exact file manifest for candidate provenance, and a canonical semantic board
digest for IPC/reopen comparisons. Sort collections by native identity and include every relevant
field. Candidate-created objects may receive new live UUIDs: maintain an explicit candidate-to-live
ID map and compare geometry as a multiset so duplicates cannot disappear in a set comparison.

Extend the existing document state, rather than introducing a competing counter. Bind revision
to document identity and a persisted generation; compare live and saved fingerprints at entry.
External mutation advances the generation. Reopen/restart must not reset it to zero. Serialize
repository mutations per document, check revision immediately before apply, and guard against
independent IPC edits during apply. If the supported IPC cannot ensure exclusive mutation, expose
the limitation and fail closed for automatic promotion; a process-local mutex alone is insufficient.

Tests: stale saved-file edit, stale unsaved IPC edit, another client mutation, restart, and two
concurrent requests with the same expected revision. Exactly one concurrent write may succeed.
An unverified save/reload result must not set `saved=true`.

### WP3: transaction correctness (depends on WP2)

Edit `scripts/kicad_promotion.py`, `scripts/kicad_live_promotion.py`,
`scripts/kicad_live_placement.py`, and `tests/test_design_contracts.py`; add focused transaction
tests if the existing module becomes unwieldy.

Model explicit states: prepared, applying, applied, saved, reopened, verified, restoring,
restored, recovery_required. Persist a journal before the first write. Mark mutation as possible
before entering apply, and attempt rollback when any apply call raises. Preflight the entire
delta, including vias, removals, locked objects, unknown types and rollback capability.

Compute additions, removals and updates; UUID retention cannot hide an update. Reject unexpected
footprint additions/removals, rule/outline/zone edits until supported. For rollback, retain complete
original payloads and created-object IDs. Checkpoint recovery must survive service restart. A
post-save `pcb_revert` loads the new state and cannot serve as the original snapshot restore.
Prove IPC can restore original identities; if it cannot, document that blocker and refuse destructive
promotion. Do not implement raw source-file replacement as a fallback.

Validation must require a parsed full report, no unaccepted new findings and completion of intended
connections. Compare rollback to its original baseline, which may contain unrouted items; do not
demand an originally imperfect board become clean. A malformed report is validation failure.
CLI DRC may inspect saved files: verify its behavior before calling a pre-save check 'live'. Use a
saved disposable snapshot for pre-save checks when necessary, and retain post-save validation.

Return rollback_attempted separately from rollback_verified. Failed restoration returns partial
with recovery_required and accurate observed state; never claim rolled_back solely because an
exception handler ran. Retry of an operation ID must return the recorded outcome, not duplicate
copper. Never roll back an unrelated concurrent edit.

Minimum failure matrix, for both routing and placement: before apply (unchanged), after first write,
after all writes, save failure, reopen failure, wrong readback, final DRC failure, restore failure,
and interrupted process after save. Assert source semantic digest, native IDs, saved readback,
unrelated-object preservation, and truthful result fields at each boundary.

### WP4: staging and orchestration (depends on WP1-WP3)

Keep the routing worker's read-only source mount, no network and absence of IPC credentials.
Add a host coordinator, proposed `scripts/kicad_routing_service.py`, using the existing MCP client
for live calls and a fixed Compose subprocess command for the worker. Do not mount the Docker
socket into a general-purpose worker or grant the worker write access to the source project.

Proposed registered coordinator tools: `routing_stage_source(expected_revision, save=false)`,
`routing_run_candidate(plan, snapshot_id)`, `routing_preview_promotion(job_id)`, and
`routing_promote_candidate(job_id, preview_id, expected_revision)`. Reuse existing names when
compatible and make breaking request changes version explicit. Do not accept arbitrary candidate
paths or caller assertions that a candidate passed. Resolve IDs inside the job root, verify the
recorded candidate hash and validation artifacts, then revalidate before promotion.

Staging: require saved source or explicit save=true, compare live revision and source hashes before
and after copying, and compare the staged manifest. Reject changes during copying. Record logical
source identity separately from snapshot paths, since run_job's snapshot hashes cannot detect live
source edits. Do not delete editor locks or call revert. Package local libraries and reject unresolved
external dependencies. Test path traversal, symlinks, partial copies and ambiguous source selection.

Promotion preview includes scope, exact delta, source/candidate digests, DRC comparison and rollback
support. Bind preview_id to all of these; any subsequent source, candidate or policy change invalidates
it. Initially refuse zones/arcs if not fully supported, reporting explicit blockers. Plane promotion
requires serialized zone settings, filled copper verification and rollback tests before advertisement.

### WP5: discovery and launchers (depends on WP4)

Update `.codex/config.toml`, `.codex/config.example.toml`, `.codex/routing.example.toml`,
`tools/kicad-routing.ps1`, `tools/kicad-routing.cmd` and README. Preserve other configuration.
Use a configured host interpreter for the coordinator; doctor must report missing dependencies
and Docker permissions. Keep stdout exclusively MCP protocol in stdio mode. Resolve paths from
the launcher location so invocation outside repository root works. Do not store tokens in plans.

Test configured allowlists as well as server tools/list. A server catalog test alone does not
prove client exposure. New configuration may need one client reload on installation; routine jobs
must not require profile switching. Record this distinction accurately. Expose unsupported live
promotion as unavailable with a reason, rather than disappearing or claiming it is enabled.

### WP6: placement intent and constraints (depends on WP2-WP4)

Edit `scripts/kicad_placement.py`, `scripts/kicad_topology.py`, live placement and shared promotion.
Use transformed courtyard/body polygons and actual Edge.Cuts region, including cutouts and rounded
corners. A bounding rectangle alone does not prove containment. Preserve original nonzero rotation
on move and rollback; do not infer missing rotation as zero. Verify layer and locked state too.

Create a real connector/module fixture alongside `tests/fixtures/placement-intent/`. Define explicit
reference-to-intent metadata with connector edge, tolerance, allowed rotations, antenna region and
copper/component exclusion. Reject ambiguous metadata. Put feedback, compensation and decoupling
distance constraints in buck-specific intent rather than assuming the general solver can infer
switching-regulator design intent. Assert the final transformed geometry, not just the returned plan.

### WP7: live API remainder (depends on WP2-WP3)

Wire helpers through actual endpoints and test discovered schemas. For no-connect and schematic
builders, preserve proven code but close endpoint/schema gaps; malformed nested requests must leave
the schematic digest unchanged. Keep ERC coordinates in mm at one parsing boundary and include
the canonical SH fixture. Verify destination creation on temporary directories, not just strings.

For selective exclusions, first inspect how pinned KiCad persists exclusions. Finding hashes may
not be native exclusion keys; preserve the native item/rule identity required by KiCad. Separate
violation_id from item_uuid selectors. Use AND across specified filter categories and OR within
each list; document and test that combination to avoid silently broadening a selection. Bind preview
to report, source revision and exact selected identities. Compare the complete saved exclusion set
to previous exclusions plus the selection. If no supported writer exists, leave execution blocked
with a precise capability reason; do not invoke the all-findings writer.

Ratsnest fallback tests must call the registered tool on KiCad 10 and then exercise its routing
consumer. Include net identity, endpoint UUID/reference/pin where available, mm positions, source
and limitations. Keep native and derived IDs distinct and reject malformed fallback evidence.

### WP8: integration, M6 gate and release (depends on WP1-WP7)

Replace fixture-only acceptance callbacks in `tests/integration_live_promotion.py` and
`tests/integration_live_placement.py` with real candidate/constraint validation. Add an isolated
test harness that verifies target paths before mutation, performs AGENTS preflight, launches a
separate disposable live service and restores only its own resources. Add a track-plus-via success
fixture, a reroute with removals, an impossible route, a rotated placement and post-save failures.

Keep buck artifacts out of mandatory tests until a reproducible sanitized fixture is checked in;
the current project is untracked. The buck regression must route from zero copper and enforce
separate power/signal width intent. For a plane fixture, verify actual zone fill and pad connection;
zone existence is insufficient. Differential tests must verify both nets, widths, gap, layers and
no shorts after readback. Impedance calculations are advisory unless backed by an appropriate
solver; do not require unavailable physical signoff to finish software M6.

M6 closes only after routing and constrained placement both pass live success, impossible-case
non-mutation, stale rejection, and verified post-save rollback on KiCad 10.0.4. Keep unsupported
object types explicit. Async jobs and dependency locks are separate release gates, not evidence
for M6. Add bounded job cancellation/recovery afterward with terminal states and journal recovery.

### Verification commands and handoff

Existing commands (run from repository root; use an available supported Python interpreter):

```powershell
python -m unittest discover -s tests -p 'test_*.py'
python -m unittest discover -s tests -p 'test_routing_jobs.py'
python -m unittest discover -s tests -p 'test_design_contracts.py'
.\tools\kicad-routing.cmd build
.\tools\kicad-routing.cmd doctor
docker compose -f compose.routing.yaml run --rm -T --entrypoint /opt/krt-python/bin/python routing /workspace/tests/integration_routing_mcp.py
docker compose -f compose.routing.yaml run --rm -T --entrypoint /opt/krt-python/bin/python routing /workspace/tests/integration_electrical_routing.py
.\tools\kicad-docker.cmd validate <disposable-project-stem> --erc --drc
git diff --check
git status --short
```

The validation placeholder must resolve to the disposable project; it is not a literal command.
Live scripts require the isolated fixture service and matching KICAD_MCP_URL. Add a single checked-in
harness command for that setup as part of WP8 and record its exact invocation. Do not run current
live fixture scripts against the user's selected board. Build before runtime tests of changed image
code. Discover configured lint/type checks from repository instructions; do not invent passing checks.

For every package record changed files, narrow tests, runtime tests, exact commands and outcomes,
environment failures separately from code failures, and remaining acceptance gaps. Do not repeat
unaffected M4 integration merely to reorganize documentation. Run affected suites after final edits,
inspect the diff, and update all cross-links/statuses consistently. A missing external capability
blocks that subcriterion; it does not justify skipping independent work packages.

## Execution checkpoint — 2026-09-10

The current working tree implements and tests the repository-side portions of WP1-WP3 and
WP6-WP7: strict routing-plan validation with credential-free capability probing, canonical
inspection/digest and same-UUID change detection, full copper/placement readback checks,
atomic failure reporting, Edge.Cuts/courtyard/connector/antenna placement constraints,
selective DRC preview semantics, pin-addressed no-connect resolution, and the KiCad 10
ratsnest fallback. The isolated pinned runtime also passed candidate routing, differential and
plane fixture regressions, live additive-track promotion, and live constrained-placement
save/reopen/readback on disposable copies.

The remaining live gates are intentionally still open: the pinned MCP surface does not provide
a safe exact-track identity/restore primitive after a successful save, does not expose a
verified schematic-save/revision endpoint, and exposes only an unsafe all-violations exclusion
writer. The routing MCP transport remains a separate read-only candidate service; a host
coordinator for saved-source staging and automatic live promotion has not been advertised.
Those capabilities fail closed rather than being represented as successful mutations. The
exact evidence for this checkpoint is archived in `docs/IMPLEMENTED_FIXES.md`.
