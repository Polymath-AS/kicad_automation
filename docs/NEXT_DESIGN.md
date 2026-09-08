# Next-design workflow and measurement plan

Use the skills at the phase where they apply. Keep one small status file containing current checkpoint, source hashes, critical constraints, open-item/DRC/parity counts, active candidate, and next action. Keep full logs and CAD geometry in files referenced by path.

1. **Preflight once:** choose the toolchain, verify libraries, smoke-test the routing round-trip and output entry point, and persist the intended rules.
2. **Design and schematic:** record requirements, reuse vetted blocks, verify pin maps, render one layout pattern before expanding it, then check native ERC and exported connectivity.
3. **Placement and critical paths:** arrange functional groups, USB/ESD/resistors, switching loops, sense routes, returns, and difficult pad escapes before ordinary routing.
4. **Bulk routing:** export a protected candidate, run the router under a bounded budget, import, refill, and compare native DRC/parity/open-item results.
5. **Residual cleanup:** group related failures, patch a coherent region, and rerun compact checks. Revisit placement when geometry makes repeated routing attempts unproductive.
6. **Release:** run the complete existing CI/export command, inspect requested outputs, and verify a consistent source/artifact manifest. Commit the checked milestone when authorized.

Return compact results at each boundary, for example: `candidate=route-03; opens 162→28; rules 0→0; parity 0→0; protected routes verified; report=...`. Counts alone are insufficient when different violations replace one another: include the DRC delta and failed critical checks.

## Highest-value implementation backlog

| Order | Extract into a reusable tool | Starting material in the supplied repo | Acceptance test |
|---|---|---|---|
| 1 | Project-aware DSN export / bounded route / SES import wrapper | `CODE/export_router.py`, `import_router.py`, `configure_routing.py` | Candidate tied to input hashes; stale SES rejected; classes preserved; protected copper unchanged; native DRC/parity run |
| 2 | Shared KiCad version adapter and board inspection summary | `build_board.py`, `finish_ground.py`, `finish_escapes.py` | Known methods/constants probed; grouped geometry and connectivity returned without full-board dumps |
| 3 | Reusable circuit blocks and schematic layout templates | `build_schematic.py`, `check_schematic.py`, local symbol/footprint libraries | Pin map checked against independent manufacturer data; readable render; no overwrite of incremental edits |
| 4 | Ground-via and fine-pitch escape candidate generator | `finish_ground.py`, `finish_escapes.py` | Batch reduces open items without new violations or violation substitutions; only candidate copy changes |
| 5 | Generalized release entry point and provenance verifier | `build_outputs.py`, `verify_outputs.py` | Invalid design fails; complete ZIP; source unchanged across checks/export; hashes match artifacts |

These source scripts contain absolute paths, component names, net names, coordinates, and checkpoint assumptions. Extract the operations into parameterized helpers; do not simply copy the scripts and rerun them on another finished design. The initial library includes the decision guidance, accounting tool, preflight probe, and DRC summarizer; the mutation tools above remain future implementation work.

## Measure savings instead of guessing

Run a controlled replay from the same committed placement checkpoint in isolated copies. Hold the model, toolchain, design constraints, protected routes, completion criteria, and artifact requirements fixed. Compare the recorded approach with the new workflow. Repeating the comparison helps account for model/router variability.

Record response count, cumulative input, cached input, uncached input, output, reasoning subset, elapsed time, compactions, failed tool operations, and human interventions. Compare quality too: native ERC/DRC/parity/open counts, protected geometry, layer use, critical routing review, complete deliverables, and source provenance. Do not count merely connecting more ordinary nets as equivalent to completing critical routes.

Use `tools/analyze_session.py` on each rollout and choose phase boundaries appropriate to that run. Add token measurements around actual tool-operation boundaries if the host exposes them; timestamp buckets from yesterday's log are not precise causal cost attribution.

A successful first iteration should reduce model round trips for routing and setup while meeting the same acceptance criteria. No percentage saving is established yet. If a new model or plugin is also introduced, benchmark it separately so its effect is distinguishable from the skill changes.

Large histories have a repeated-input cost, but starting fresh can lose cache and require design reconstruction. Use explicit milestone handoffs when helpful, carrying the status file and relevant artifacts; do not reset reflexively after every check. The observed cache-hit rate was already 97.2%, so the main target is fewer unnecessary responses and smaller new tool outputs, not simply increasing cache hits.
