# KiCadRoutingTools integration and remaining plan

## Architecture and supported scope

The optional routing service integrates [drandyhaas/KiCadRoutingTools](https://github.com/drandyhaas/KiCadRoutingTools)
at commit `529f873d4c4c20493b1fa786cc9b42ce6cce2945` (VERSION 0.22.0).
It compiles the Rust engine using upstream `build_router.py --from-source`, verifies that
Cargo.lock did not change, and uses a separate Python environment. The upstream MIT license is
retained at `/opt/KiCadRoutingTools/LICENSE`. Python and Rust sources come from the same revision;
jobs do not download a latest release or rebuild the router.

Upstream provides obstacle-aware A* routing, rip-up/reroute, differential routing and plane
operations. This adapter exposes a bounded subset of its CLI through both repository commands
and a separate MCP server. It does not install the GUI plugin or upstream's optional AI agents.

```text
CLI / routing MCP
  -> validate typed plan
  -> copy saved project from read-only /workspace
  -> baseline ERC + DRC
  -> planes / diff / route on staged copies
       -> restore original project rules and schematic after EACH stage
       -> run independent KiCad ERC + DRC after EACH stage
  -> compare findings -> result.json + candidate project under /jobs

Existing KiCad MCP Pro -> live IPC editing, placement and saving
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
docker compose -f compose.routing.yaml build routing
docker compose -f compose.routing.yaml run --rm -T routing doctor
```

`doctor` checks source revision and required scripts. Image construction also runs the upstream
router's `--help`, which imports the compiled engine and performs its startup dependency checks.

## 2. Prepare the source project

1. Finish schematic connectivity, placement, board outline, keepouts and manufacturing rules.
   The router cannot fix an incorrect circuit or infer the ESP32 antenna requirements.
2. Confirm the selected live document with `kicad_get_server_info`, `kicad_get_project_info`, and
   `pcb_get_board_summary`; persist it with `pcb_save`.
3. Run `.\tools\kicad-docker.cmd validate <project-stem> --erc --drc` and inspect the baseline.
4. Save and close the editor, or stop the container owning the project. Source directories with
   `~*.lck` files are refused. Do not remove another live session's lock.
5. Keep the matching `.kicad_pro`, `.kicad_sch` and `.kicad_pcb` in a dedicated project directory.
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
  "timeout_seconds": 600,
  "steps": [
    {"operation": "planes", "nets": ["GND"], "layers": ["B.Cu"]},
    {"operation": "diff", "nets": ["USB_DP", "USB_DM"], "layers": ["F.Cu"]},
    {"operation": "route", "nets": ["*", "!USB_DP", "!USB_DM"], "layers": ["F.Cu", "B.Cu"]}
  ]
}
```

Upstream recommends pouring planes first; later routing finalizes plane connectivity. Excluding
handled differential nets from the generic route step preserves the intended sequence.

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
limit. Timed-out process groups are killed and logs preserved. Unknown arguments, shell commands,
in-place overwrite switches, non-copper layers and invalid numbers fail during preflight.

Differential gap/impedance, explicit pair maps, power-net widths, fanout and length matching are
not exposed in this first adapter. Do not treat a default differential route as high-speed signoff.

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
summary. There is no automatic live promotion command yet. Preserve the original until reviewed.

## 5. MCP tool access

After building, `.\tools\kicad-routing.cmd mcp` starts a stdio MCP server. Its JSON-RPC traffic is
on stdin/stdout; Compose diagnostics go to stderr. Add `.codex/routing.example.toml` to the MCP
client's project configuration and reload once. This does not require changing MCP Pro profiles.

1. `routing_tools_info()` reports backend/revision and source/output boundaries.
2. `routing_run_candidate(plan)` accepts a typed nested plan and returns the job result.
3. `routing_job_result(job_id)` reads a persisted result after reconnecting.

Calls are synchronous. Use the CLI for jobs longer than the client's timeout. Disconnecting is
not proof of completion. A killed container may leave a `running` checkpoint; treat it as
incomplete and start a new job. Automatic resume/cancellation is a later milestone.

## Verification and reproduction

```powershell
python -m unittest discover -s tests -p 'test_*.py'
docker compose -f compose.routing.yaml run --rm -T --entrypoint /opt/krt-python/bin/python routing /workspace/tests/integration_routing_mcp.py
```

Verified 2026-09-09 using KiCad 10.0.4 and the pinned Rust engine:

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

`scripts/build_routing_fixture.py` records the MCP creation procedure and refuses existing
projects by default. The checked-in project triplet is sufficient for repeatable routing tests;
normal tests do not regenerate it. `--finish-existing` is a diagnostic recovery mode, not a
general-purpose idempotent design builder. The two footprint warnings originate in schematic
sync losing the library-qualified footprint identifier; that MCP defect remains open.

The MCP SDK emits a Pydantic `lifespan` forward-reference warning on startup with the current
dependency resolution; protocol tests pass, but dependency-lock hardening should resolve it.
Differential and plane operations have dispatcher support, not yet real electrical fixture
coverage. Neither this smoke test nor an ERC/DRC pass proves an ESP32 board production-ready.

## Remaining implementation milestones

### R1 — Candidate routing backend (this change)

Pinned source/build, typed route/diff/planes dispatcher, CLI/MCP entry points, read-only source,
per-stage validation, original-rule restoration, evidence and error handling. Test real copper
creation as well as missing output, invalid options and regression detection. Record which
operations have electrical integration coverage; generic routing tests do not prove differential
signal integrity or complex plane behavior.

### R2 — Electrical routing controls

Add explicit differential pair identities, gap/impedance/stackup inputs, power width maps, fanout
and guide/keepout settings. Read the pinned upstream schemas, expose typed controls, reject
inconsistent inputs, and add one real fixture per operation. Acceptance: selected nets route with
correct widths/clearances; unrelated nets and pin assignments remain unchanged.

### R3 — Reviewed live promotion and rollback

Compute a geometry-aware copper delta and separate footprint movement report. Reject stale input,
changed net assignments and removed unrelated copper. Apply supported changes through MCP Pro
IPC within a checkpoint/undo boundary. Save, re-read and validate; restore via IPC on failure and
verify restoration. Acceptance: interrupted import preserves original design; accepted changes
survive reopening. This is the outstanding transactional portion of M6.

### R4 — Placement intent and ESP32 acceptance

Define hard constraints for USB connector position, antenna keepout, edges, decoupling and header
access. Grade placement before routing, establish real USB pair topology and electrical rules,
then run the ESP32 plan. Review renders and manufacturing outputs. Router completion alone does
not establish production readiness of the current ESP32 board.

### R5 — Remaining MCP contract fixes

Implement pin-addressed no-connects, precise schematic-builder schemas, save/revision semantics,
partial-success results, KiCad 10 ratsnest fallback and selective DRC exclusions. KiCadRoutingTools
does not solve those APIs. Keep M4 open for the original pad-to-pad helper; candidate routing is
an alternative backend with a different persistence model.

### R6 — Runtime and release hardening

Add asynchronous execution/cancellation, transitive dependency locks, CI integration artifacts,
board-size/resource calibration and broader platform tests. Run the routing fixture suite before
changing upstream SHA, version label or adapter behavior. Keep each job's original revision in
its evidence so results remain attributable.
