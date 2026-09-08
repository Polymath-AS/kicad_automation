# MCP options and potential savings

Evaluated 2026-09-08 against the recorded design session. No candidate server was installed or benchmarked. Capability statements below come from upstream documentation, not verified behavior on this machine.

## What an MCP can save

MCP supplies a callable interface. Savings depend on the operations behind that interface: batch edits, reliable API handling, bounded jobs, file-based inputs, and compact results. A CLI wrapper providing identical operations can deliver similar benefits. An MCP exposing one trace segment per model call may preserve the original bottleneck.

The source session already used Freerouting. Replacing its shell invocation with MCP must not be credited with all the benefit of introducing an autorouter from scratch. Its directly identifiable setup/bulk-routing buckets account for only 6,527 of 155,807 generated tokens, although routing also occurred during later cleanup.

## Candidates

| Candidate | Documented fit | Evaluation decision |
|---|---|---|
| [Freerouting official MCP](https://github.com/freerouting/freerouting/blob/master/docs/API/MCP.md) | `autoroute_board` accepts file paths, a timeout and requested output formats; combines routing with SES/diagnostic retrieval | First routing-interface candidate; test local mode. Native KiCad export/import/refill/DRC must still be provided and verified |
| [mixelpixx/KiCAD-MCP-Server](https://github.com/mixelpixx/KiCAD-MCP-Server) | Documents batch schematic authoring, PCB component batches, geometry queries, Freerouting integration, exports, and Windows setup | First broad KiCad candidate to benchmark; check actual batch support for the selected IPC/SWIG backend and pin the session to one board |
| [NiRuLabs/kicad-mcp-server](https://github.com/NiRuLabs/kicad-mcp-server) | PCB queries, pathfinding, track/via edits and transactions; schematic capture marked experimental and hidden by default | Alternative for focused PCB interaction, not the first choice for schematic cost reduction. Verify advertised version requirements against actual KiCad IPC availability |
| Small project-specific orchestration MCP | Proposed `preflight`, `check_candidate`, `route_candidate`, `export_release` operations around tested scripts | Likely useful complement, but requires implementation. Same functions can initially run as CLI scripts to isolate the value of MCP packaging |

The broad server's [tool inventory](https://github.com/mixelpixx/KiCAD-MCP-Server/blob/main/docs/TOOL_INVENTORY.md) lists `batch_move_components` and filtered geometry queries; its README documents batch schematic edits and connections. This is a capability shortlist, not an endorsement based on production testing. Do not run two competing editing servers against the same active board.

Freerouting's guide advertises reducing its own 6–7-step job workflow to one composite call. That is an upstream workflow claim, not a 6–7x saving for the whole design. Its public API bridge and local engine are separate deployment modes; the existing 1.6.2 JAR should not be assumed to offer the modern MCP tools.

## Transparent savings scenario

Baseline: **155,807 output tokens**, including 47,091 reasoning tokens. The following reduction assumptions are deliberately hypothetical. They are neither benchmark results nor confidence intervals. Four non-overlapping phase groups are used to avoid adding overlapping tool benefits twice.

| Work affected | Recorded output | Assumed reduction within this work | Reduction of whole-session output |
|---|---:|---:|---:|
| Router discovery/rule repair + bulk routing | 6,527 | 50–75% | 2.1–3.1% |
| Schematic construction + placement | 55,061 | 25–50% | 8.8–17.7% |
| Ground checkpoint + connectivity/CI cleanup | 21,678 | 10–25% | 1.4–3.5% |
| Final exports and documentation | 28,958 | 25–50% | 4.6–9.3% |

Arithmetic: sum(recorded phase output × assumed fractional reduction).

Under those assumptions, the reduction is **26,436–52,324 generated tokens**, or **17–34%**. Remaining generated usage would be approximately **103,000–129,000 tokens**. For planning, round the opportunity to roughly **15–35%**, conditional on working batch operations and reusable workflows. There is no evidence establishing these particular reduction assumptions yet. No saving is assigned to the planning, initial critical manual routing or USB/thermal phase, although some tooling might help them too.

The range excludes new server/schema overhead, implementation/setup tokens, migration failures, and any additional rework. It also excludes potential downstream benefits from smaller histories or fewer compactions. Real net savings can be smaller, zero, or negative. An installation-only comparison cannot claim the benefit of circuit templates or CAD algorithms that have not been implemented.

Do not apply this output-token percentage directly to the 28 million cumulative input figure, elapsed time, or subscription quota. Input caching and response count change independently. Measure each separately on replay. The original cache rate was already 97.2%.

## Toolchain shape to benchmark

Use one verified KiCad editing backend, one routing engine, and a few composite operations:

- `inspect_project`: versions, saved rules, counts, selected geometry and missing prerequisites.
- `apply_component_batch`: validated edits to a candidate, with one save and explicit change summary.
- `route_candidate`: protected export, bounded router run, fresh import/refill and native DRC.
- `check_candidate`: current ERC/DRC/parity and added/resolved failures, with links to full reports.
- `export_release`: complete existing output pipeline and consistent source/artifact hashes.

Those names describe proposed wrapper contracts, not tools currently installed here. Pass board paths and selected references/nets; return concise structured summaries. Keep full-board geometry, base64 files and complete logs out of the model context except when needed for diagnosis.

Keep the exposed tool surface selective. OpenAI's [tool-search documentation](https://developers.openai.com/api/docs/guides/tools-tool-search) supports loading function/MCP schemas on demand. A server's own keyword-search command does not prove the host deferred its other schemas; inspect the actual integration rather than assuming all catalog overhead disappears.

Benchmark in this order: existing scripts; equivalent operations through MCP; then composite/batch operations through MCP. Use the same project checkpoint, constraints and deliverables. This separates transport/interface savings from backend improvements. Record initial setup usage separately and amortize it over subsequent designs. Require unchanged protected routes, valid persisted rules, native checks, readable schematics and complete exports before accepting any token reduction.
