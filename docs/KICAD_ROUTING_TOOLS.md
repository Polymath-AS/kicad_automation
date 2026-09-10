# KiCadRoutingTools integration and remaining plan

## Architecture and supported scope

The optional routing service integrates [drandyhaas/KiCadRoutingTools](https://github.com/drandyhaas/KiCadRoutingTools)
at commit `529f873d4c4c20493b1fa786cc9b42ce6cce2945` (VERSION 0.22.0).
It compiles the Rust engine using upstream `build_router.py --from-source`, verifies that
Cargo.lock did not change, and uses a separate Python environment. The upstream MIT license is
retained at `/opt/KiCadRoutingTools/LICENSE`. Python and Rust sources come from the same revision;
jobs do not download a latest release or rebuild the router.

Upstream provides placement optimization, obstacle-aware A* routing, rip-up/reroute,
differential routing and plane operations. This adapter exposes a bounded subset of its CLI through both repository commands
and a separate MCP server. It does not install the GUI plugin or upstream's optional AI agents.

```text
CLI / routing MCP
  -> validate typed plan
  -> copy saved project from read-only /workspace
  -> baseline ERC + DRC
  -> bounded placement refinement on a staged copy (when requested)
  -> planes / diff / route on successive staged copies
       -> restore original project rules and schematic after EACH stage
       -> run independent KiCad ERC + DRC after EACH stage
  -> compare findings -> result.json + candidate project under /jobs

Existing KiCad MCP Pro -> live IPC editing, initial placement and saving
```

The routing container has no network, a read-only root filesystem and source mount, a writable
job mount, 4 GiB memory, two CPUs and a 256-process limit. Temporary storage is capped at 512 MiB.
Subprocesses receive an explicit environment that excludes inherited MCP credentials, since
upstream prints environment settings in diagnostic logs.

The batch file-writing boundary is explicit: upstream edits only generated candidate copies.
The adapter never overwrites the source project and never imports it automatically into live IPC.
Original-rule validation is essential because upstream can adjust `.kicad_pro` constraints while
routing. A process exit code alone cannot establish electrical correctness.

## 1. Build and check

From the repository root on Windows with Docker Desktop running:

```powershell
.\tools\kicad-routing.cmd build
.\tools\kicad-routing.cmd doctor
```

The build command first builds the existing KiCad image, then the routing image. The initial build
needs internet access for source, the Rust compiler image, Cargo crates and Python dependencies.
Allow several minutes and several GiB. Host Rust and host Python packages are not required by
the launcher. Subsequent routing jobs run offline. Direct Python dependencies are pinned;
transitive pip packages and Debian packages are not yet fully locked.

Equivalent Docker commands (create `.kicad-automation/routing/` before first use):

```powershell
docker compose -f compose.yaml build kicad
docker compose --project-name kicad-routing-automation -f compose.routing.yaml build routing
docker compose --project-name kicad-routing-automation -f compose.routing.yaml run --rm -T routing doctor
```

`doctor` checks source revision and required scripts. Image construction also runs the upstream
router's `--help`, which imports the compiled engine and performs its startup dependency checks.

## 2. Prepare the source project

1. Finish schematic connectivity, initial placement, board outline, keepouts and manufacturing rules.
   The router cannot fix an incorrect circuit or infer the ESP32 antenna requirements.
2. Confirm the selected live document with `kicad_get_server_info`, `kicad_get_project_info`, and
   `pcb_get_board_summary`; persist it with `pcb_save`.
3. Add a conservative `placement` stage to refine the existing unrouted placement. Declare locks
   for connectors, mounting holes, RF/mechanical-critical parts, and pass project-relative intent
   when available. The placer is an optimizer, not an unaided from-scratch placer.
4. Run `.\tools\kicad-docker.cmd validate <project-stem> --erc --drc` and inspect the baseline.
5. Save and close the editor, or stop the container owning the project. Source directories with
   `~*.lck` files are refused. Do not remove another live session's lock.
6. Keep the matching `.kicad_pro`, `.kicad_sch` and `.kicad_pcb` in a dedicated project directory.
   Hierarchical sheets and project-local libraries are copied along with them. Symlinks are
   rejected: package those dependencies explicitly. External absolute library paths may not
   resolve inside Docker; validation must succeed before any candidate can be marked clean.

The snapshot uses saved files, not unsaved editor memory. The source mount is read-only. The
adapter excludes `.git`, `.history`, `.kicad-automation`, `output`, `node_modules`, editor lock
files and `.kicad_prl` from copies. Job storage must be outside the source project directory.
Source-change detection hashes board, schematic, project and custom-rule files recursively;
it is not a full manifest of external library dependencies. The disposable KiCad configuration
is seeded with the image's standard symbol/footprint library tables before validation.

## 3. Define a routing plan

Start with `routing-plans/smoke.json` for the two-terminal integration fixture. For a real board,
copy `routing-plans/esp32.example.json`, then replace paths and net names from actual netlist
inspection. The example USB names are placeholders, not a validated ESP32 USB design. The current
ESP32 schematic has separate connector-side and chip-side DP/DM nets; pairing must reflect that.

```json
{
  "project": "CAD/my-board/my-board.kicad_pcb",
  "schema_version": 2,
  "timeout_seconds": 600,
  "placement": {
    "mode": "optimize",
    "move_refs": ["U3", "R12", "R13", "C7", "C8"],
    "max_displacement": 3,
    "lock": ["J*", "H*"],
    "ignore_nets": ["GND", "+3V3"]
  },
  "steps": [
    {"operation": "planes", "nets": ["GND"], "layers": ["B.Cu"]},
    {"operation": "diff", "nets": ["USB_DP", "USB_DM"], "layers": ["F.Cu"]},
    {"operation": "route", "nets": ["*", "!USB_DP", "!USB_DM"], "layers": ["F.Cu", "B.Cu"]}
  ]
}
```

Upstream recommends pouring planes first; later routing finalizes plane connectivity. Excluding
handled differential nets from the generic route step preserves the intended sequence.
When `placement` is present and enabled, `place_optimize.py` always runs before those copper
steps. Its conservative defaults are 3 mm maximum displacement, length weight 0.3, crossing
penalty 30, halo coefficient 0.15, halo weight 2, and edge halo 2 mm. Placement is refused by
upstream on routed boards unless explicitly overridden; this adapter intentionally does not
expose that unsafe override.

Placement accepts `max_displacement`, `swap_max_displacement`, `step`, `grid_step`, `clearance`,
`board_edge_clearance`, `crossing_penalty`, `length_weight`, `halo_coef`, `halo_weight`,
`edge_halo`, `max_passes`, `lock`, `ignore_nets`, project-relative `intent`, `no_rotate`, and
`no_swap`. Unknown options, path escapes, nonfinite values, and a swap displacement larger than
the total displacement cap fail before staging.

Use `move_refs` for an exact component allowlist. In `mode: "optimize"` (the default), the
adapter reads references through the pinned KiCadRoutingTools parser, rejects missing references,
and adds every non-selected footprint to the optimizer's lock list. This binds the public CLI to
the internal `quench(..., move_refs={...})` behavior without maintaining a fork of the upstream
placer. An explicit `lock` pattern that also matches a selected reference is rejected.

Use `mode: "reseat"` when selected parts should be lifted and placed again from scratch:

```json
"placement": {
  "mode": "reseat",
  "move_refs": ["U3", "R12", "R13", "C7", "C8"],
  "intent": "floorplan.json",
  "max_displacement": 3
}
```

This invokes `place_seed.py --reseat ... --evict-depth 0`, requires reviewed intent, and holds
all non-selected parts fixed. Eviction is deliberately disabled so the candidate cannot move an
unselected blocker. Reseat mode rejects optimizer-only controls rather than silently ignoring them.

| Field | Meaning | Accepted values |
|---|---|---|
| `operation` | Upstream operation | `route`, `diff`, `planes` |
| `nets` | Ordered names/wildcards/exclusions | Explicit nonempty list; names starting with `-` unsupported |
| `layers` | Ordered copper layers | `F.Cu`, `F_Cu`, `BL_F_Cu`, etc. |
| `track_width` | Optional trace width, mm | 0.05–10 |
| `clearance` | Optional requested routing clearance, mm | 0.05–10; original rules remain authoritative |
| `via_size` | Optional diameter, mm | 0.1–10 |
| `via_drill` | Optional drill, mm | 0.05–5; less than supplied diameter |
| `grid_step` | Grid resolution, mm | 0.025–1 |

Omitted numeric values use upstream's board/net-class defaults. Plans contain 1–8 steps;
`timeout_seconds` is 10–3600 per routing step. Each ERC/DRC subprocess has a separate 120-second
limit. Timed-out process groups are killed and logs preserved. Typed plans additionally support
`diff_pair_gap`, `impedance`, `coplanar_gap`, `length_match_tolerance`, `zone_clearance`,
`power_nets`, `power_nets_widths`, `stitch_vias`, `add_gnd_vias`, `gnd_via_net`, and
`gnd_via_distance`. Differential controls are accepted only on `diff` steps and plane controls
only on `planes` steps; numeric ranges and per-net width list lengths are validated before any
candidate is staged. Unknown arguments, shell commands, in-place overwrite switches, non-copper
layers and invalid numbers fail during preflight.

These controls are routing hints, not a substitute for final stackup/signoff review. The pinned
upstream CLI does not expose full fanout/keepout semantics or a native impedance solver.

## 4. Run and interpret evidence

```powershell
.\tools\kicad-routing.cmd run routing-plans/smoke.json
# Alternate source mount; plan path is relative to that mount:
.\tools\kicad-routing.ps1 run plans/route.json -ProjectRoot C:\CAD
```

Jobs persist at `.kicad-automation/routing/<job-id>/`, mapped to `/jobs/<job-id>`:

- `result.json`: normalized plan, revision, source/candidate hashes, exact commands, exit codes,
  findings, baseline/final comparison and `applied: false`.
- `baseline/`: initial project snapshot; `baseline-checks/`: independent ERC/DRC reports and logs.
- `input-NN/`: disposable upstream input, protecting the baseline if upstream edits input siblings.
- `step-NN/`: successive complete candidate projects; `step-NN.log`: routing output;
  `step-NN-checks/`: validation evidence after that step.

Original schematic, project and custom rule files are restored before every stage's validation.
New contract files created by upstream are removed only from that candidate. This prevents
weakened rules or schematic rewrites from hiding regressions. The original source is unchanged.

| Status | Meaning | Action |
|---|---|---|
| `candidate_clean` | Final ERC and DRC report zero findings | Review layout and design intent |
| `needs_review` | Findings remain without detected regression | Inspect remaining errors/connections and rerun |
| `rejected` | New nonconnectivity finding, more unconnected items, or source changed | Inspect evidence; keep original |
| `error` | Tool failure, missing output, timeout or validator failure | Fix cause and start a new job |

A nonzero router exit cannot pass. An empty board with no matching nets is an expected error;
`routing-plans/minimal.json` is a negative test, not a routing success demonstration. Finding
comparison uses full contents as a multiset, so equal counts cannot hide replacement errors.
UUID/coordinate changes may conservatively classify a moved finding as new.

Open the candidate's `.kicad_pro` separately for visual review. To continue editing through IPC,
restart KiCad MCP Pro with that candidate board as the target, then recheck project info and board
summary. Reviewed live promotion is available through `scripts/kicad_live_promotion.py` for the
supported single-track IPC path. It applies only the validated copper delta, saves, reloads through
`pcb_revert`, reads tracks back, checks net identity, and runs post-promotion validation. The
same transaction boundary is now bound to `pcb_move_footprint` by
`scripts/kicad_live_placement.py`, with explicit position restoration after post-save failure.
The generic transaction supports injected failure/rollback callbacks; the pinned upstream MCP
surface still does not expose a safe exact-track identity/restore primitive, so automatic rollback
after a successful copper save remains an explicit integration boundary rather than being claimed
implicitly.

## 5. MCP tool access

After building, `.\tools\kicad-routing.cmd mcp` starts a stdio MCP server. Its JSON-RPC traffic is
on stdin/stdout; Compose diagnostics go to stderr. The checked-in `.codex/config.toml` registers
the optional routing server alongside the live KiCad server; `.codex/routing.example.toml` remains
the minimal copyable fragment for another client. Installation may require one client catalog
reload, but routine routing jobs do not require profile switching. If Docker or the coordinator
is unavailable, routing tools remain discoverable with an explicit unavailable reason.

1. `routing_tools_info()` reports backend/revision, source/output boundaries and whether placement
   refinement, topology preview, dry-run blocking reports and live promotion are available.
2. `routing_run_candidate(plan)` accepts a typed placement-plus-routing plan and returns the job result.
3. `routing_plan_trace(board, request)` is a pure structured-board dry-run that returns planned
   segments or blocking object UUIDs/coordinates without writing a board.
4. `routing_job_result(job_id)` reads a persisted result after reconnecting.

Calls are synchronous. Use the CLI for jobs longer than the client's timeout. Disconnecting is
not proof of completion. A killed container may leave a `running` checkpoint; treat it as
incomplete and start a new job. Automatic resume/cancellation is a later milestone.

### Policy schema and capability probing

Plans without `schema_version` retain legacy v1 argument behavior and return a deprecation warning.
Schema v2 defaults each operation to `fab_tier=standard`, `escalation=off`,
`strict_sizes=true`, `no_fix_drc_settings=true`, and bounded iteration budgets. It accepts only the
typed policy fields listed in the remaining-fixes plan; unknown, nonfinite, conflicting or
operation-incompatible values fail before staging. The adapter runs each pinned router's sanitized
`--help` probe before a v2 job and refuses options that the installed parser does not advertise.
Per-stage results retain logs, policy, optional iteration metrics (unknown is represented as null),
contract hashes and regression comparisons. A strict fabrication-policy exit is reported as policy
rejection, not as a successful candidate or an unclassified crash.

## Verification and reproduction

```powershell
python -m unittest discover -s tests -p 'test_*.py'
docker compose --project-name kicad-routing-automation -f compose.routing.yaml run --rm -T --entrypoint /opt/krt-python/bin/python routing /workspace/tests/integration_routing_mcp.py
```

Verified 2026-09-10 using KiCad 10.0.4 and the pinned Rust engine:

- CLI generic routing created track segments; unconnected items went from 1 to 0.
- Real MCP initialization, nested plan schema, backend information, candidate routing, persisted
  result retrieval and invalid job-ID rejection passed (`20260909-182724-8a0d8a1964`).
- Final ERC: 0 findings. Final DRC: 2 existing `footprint_symbol_mismatch` warnings, down from
  3 total findings before routing. No new findings. Result: `needs_review`, never clean.
- Source contract unchanged; candidate not applied. Upstream attempted to change project-rule
  floors; original rules were restored before independent validation.
- The fixture was created, synced, positioned and saved via the live MCP server, with repository
  validation after mutations. Final live summary: 2 footprints, 2 nets (including empty net),
  0 tracks/vias/zones before batch routing. `pcb_save` confirmed success. The fixture service was
  stopped to release its lock before routing. The ESP32 project was not modified.

Latest implementation verification also rebuilt both images after the transaction/parser changes,
ran `routing doctor`, and passed the stdio MCP and differential/plane integration commands. A
separate disposable KiCad service on port 3336 passed `tests/integration_live_promotion.py` and
`tests/integration_live_placement.py`; after teardown/restart, `pcb_get_footprints` read J1 back at
`(35.00, 30.00)`. The required disposable validation command returned ERC 0 but exit 1 for the
fixture's expected four unrouted nets and two known footprint-symbol mismatch warnings. That is
recorded as a design-result failure, not hidden as a clean DRC result. The user ESP32 service on
3334 remained running and was not used for mutation.

`scripts/build_routing_fixture.py` records the MCP creation procedure and refuses existing
projects by default. The checked-in project triplet is sufficient for repeatable routing tests;
normal tests do not regenerate it. `--finish-existing` is a diagnostic recovery mode, not a
general-purpose idempotent design builder. The two footprint warnings originate in schematic
sync losing the library-qualified footprint identifier in this historical fixture. New image
builds apply a narrowly scoped kicad-mcp-pro 3.34.0 renderer patch and exercise it in
`docker/tests/verify_kicad_mcp_compat.py`.

The MCP SDK emits a Pydantic `lifespan` forward-reference warning on startup with the current
dependency resolution; protocol tests pass, but dependency-lock hardening should resolve it.
`tests/integration_electrical_routing.py` exercises real differential and plane fixtures. The
differential candidate routed both `USB_D_P`/`USB_D_N` members and reduced unconnected findings
4->2; the plane candidate created a GND B.Cu zone and preserved the baseline unconnected count.
Both correctly return `needs_review` because unrelated fixture nets remain. Neither these
disposable fixtures nor an ERC/DRC pass proves an ESP32 board production-ready.

`tests/integration_live_promotion.py` exercises the real pinned IPC promotion path on a disposable
copy: candidate segment, correct `USB_D_P` net, save, `pcb_revert` reopen, live readback and
structured `saved=true`, `dirty=false`, `readback_verified=true` result. Repository validation
reports ERC 0 and the expected remaining DRC fixture findings.

`tests/integration_live_placement.py` exercises the corresponding constrained position promotion
for J1: save, `pcb_revert` reopen, live readback, service restart durability, and the same
structured state fields. The validator reports ERC 0 and only the fixture's expected DRC findings.

## Remaining implementation milestones

The authoritative ordering, acceptance gates, and documentation-archive policy for remaining
work are in [`REMAINING_FIXES_PLAN.md`](REMAINING_FIXES_PLAN.md). The sections below retain the
routing-specific milestone context; they are not a separate backlog.

### R1 — Candidate routing backend (this change)

Pinned source/build, typed route/diff/planes dispatcher, CLI/MCP entry points, read-only source,
per-stage validation, original-rule restoration, evidence and error handling. Test real copper
creation as well as missing output, invalid options and regression detection. Record which
operations have electrical integration coverage; generic routing tests do not prove differential
signal integrity or complex plane behavior.

### R2 — Electrical routing controls

Typed differential/plane controls, validation, and one real fixture per operation are implemented.
The remaining acceptance gap is live signoff for stackup impedance/length matching and broader
fanout/keepout semantics than the pinned upstream CLI exposes.

### R3 — Reviewed live promotion and rollback

`scripts/kicad_promotion.py` computes a geometry-aware copper delta and separate footprint movement
report, rejects stale input and unsafe removals, and supplies checkpoint/restore hooks around IPC
apply, save, re-read and validation. `scripts/kicad_live_promotion.py` binds the supported
single-track MCP operations and has a real pinned-runtime success regression. The new
`scripts/kicad_live_placement.py` binds constrained position promotion and explicit restoration;
`tests/integration_live_placement.py` verifies saved readback after service restart.
`scripts/kicad_topology.py` supplies the analogous atomic route adapter and
`scripts/kicad_placement.py` supplies non-mutating hard-constraint placement failure. Saved-source
rollback for copper remains open because the upstream surface lacks durable exact-track identity.

### R4 — Placement intent and ESP32 acceptance

Repository hard constraints cover Edge.Cuts bounds, body/courtyard overlap, locked parts,
connector-edge and antenna keepouts. `tests/fixtures/placement-intent/placement_intent.json`
provides deterministic connector/RF intent regression data, and a pinned disposable live
placement fixture verifies source-board promotion, save, reopen, and readback. Live
rotation/UUID parity remains to be exercised; router completion alone does not establish
production readiness of the current ESP32 board.

### R5 — Remaining MCP contract fixes

Pin-addressed no-connects, precise schematic-builder schemas, adapter revision semantics,
partial-success results, and the KiCad 10 ratsnest fallback are implemented and live-tested where
the pinned surface permits. Selective DRC preview is implemented and fails closed; live execution
remains blocked by the pinned upstream all-violations-only exclusion API. M4 is complete for the
original pad-to-pad helper; candidate routing is an alternative backend with a different
persistence model.

### R6 — Runtime and release hardening

Add asynchronous execution/cancellation, transitive dependency locks, CI integration artifacts,
board-size/resource calibration and broader platform tests. Run the routing fixture suite before
changing upstream SHA, version label or adapter behavior. Keep each job's original revision in
its evidence so results remain attributable.
