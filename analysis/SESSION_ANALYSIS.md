# Where the KiCad session spent tokens

The strongest opportunity is to give the model **larger, reliable CAD operations with compact results**: verify the environment and rules once, prepare critical routing geometry, autoroute ordinary connections, fix residual violations in groups, and export a complete package at a stable milestone. Shorter chat replies alone would miss most of the opportunity.

This analysis covers the supplied rollout from **08:46 to 11:16 UTC on 2026-09-07** (10:46–13:16 Oslo time), and the supplied repository through commit `a36fb00`. Later repository commits extend beyond the recorded session. It is one design, so improvement priorities are evidence-based hypotheses, not measured savings from a controlled comparison.

## What the counters actually say

| Measurement | Recorded value |
|---|---:|
| Model responses with unique usage records | 226 |
| Cumulative input tokens | 28,059,235 |
| Cached input, included in input above | 27,278,976 (97.22%) |
| Uncached input | 780,259 |
| Output tokens | 155,807 |
| Reasoning output, included in output above | 47,091 |
| Remaining output, including tool-call text | 108,716 |
| Input + output | 28,215,042 |
| Shell command completion records | 311 |
| Nonzero shell exits | 34 |
| File-change events / image-view events | 62 / 15 |
| Context compactions | 2 |

Input is repeatedly counted as context is supplied to subsequent model responses. The 28 million figure is not unique design content, and cached tokens should not be priced as uncached input. Likewise, reasoning is a subset of output, not an extra amount to add. This log does not establish a monetary bill or the exact conversion to subscription limits. [Official prompt-caching documentation](https://developers.openai.com/api/docs/guides/prompt-caching) distinguishes these usage categories and their pricing treatment.

The analyzer sums `token_usage_record.payload.usage` once per `response_id`. Its sum exactly matches the final `thread_token_usage`. It does **not** also add mirrored `event_msg/token_count` totals, cumulative turn totals, duplicated messages inside compaction history, or encrypted-reasoning bytes.

The final event counter reports 27,734,238 total tokens, which is 480,804 lower. The two usage records immediately preceding compactions account for that difference exactly: 468,886 input + 11,918 output. Their uncached input totals 100,118. Compaction is therefore included in the canonical totals and in its surrounding phase; the counters are not interchangeable.

Reproducible evidence: [summary](session/summary.json), [per-response usage](session/usage.jsonl), [command ledger](session/commands.jsonl), [message ledger](session/messages.jsonl), [phase definitions](phases.json), and [analyzer](../tools/analyze_session.py). The raw input is `references/rollout-2026-09-07T10-46-19-01a07b0c-0257-74a1-a03d-98d563f35507.jsonl`; line numbers below refer to that file.

## Usage by work phase

| Phase | Responses | Input, including cache | Uncached input | Output |
|---|---:|---:|---:|---:|
| Planning and component selection | 13 | 368,190 | 52,542 | 5,283 |
| Schematic construction and review | 37 | 4,086,255 | 124,911 | 30,800 |
| Placement and review | 29 | 5,612,267 | 104,683 | 24,261 |
| Initial manual routing | 28 | 1,870,144 | 160,832 | 18,421 |
| Router discovery and rule repair | 17 | 1,313,563 | 17,051 | 4,069 |
| Bulk autorouting and import | 11 | 985,270 | 12,342 | 2,458 |
| Initial ground cleanup and checkpoint | 16 | 1,729,636 | 23,780 | 6,581 |
| Remaining connectivity and CI repair | 24 | 3,158,745 | 149,977 | 15,097 |
| USB refinement and thermal copper | 23 | 4,145,153 | 75,649 | 19,879 |
| Final outputs and documentation | 28 | 4,790,012 | 58,492 | 28,958 |

These are editorial timestamp buckets chosen from user requests, progress milestones and a commit. They attribute complete model responses, not individual reasoning tokens to particular commands. Some work overlaps phases, and input includes inherited context. Manual routing includes the first compaction; final outputs include the second. A cache miss also contributes 114,481 uncached input to a single response at line 1432 during connectivity cleanup. Thus, uncached-input differences alone cannot establish that one CAD action is intrinsically expensive.

Schematic and placement together account for 55,061 output tokens (35.3% of all output) and 66 responses. Final output/documentation adds 28,958 output tokens and 28 responses. The target is broader than routing alone.

## Autorouting: the observed improvement

| Checkpoint | Open items | Evidence |
|---|---:|---|
| Placement ready | 208 | Message line 669; placement commit `2561262` |
| Initial buck/DAC traces | 190 | Line 818; commit `73e48d3` |
| Feedback, sense paths and ground returns | 162 | Lines 887–898; commit `2b1e08d` |
| Bulk router candidate accepted | 28 | Line 1135; commit `7b6780f` |
| First ground cleanup checkpoint | 27 | Lines 1216–1253; commit `ae18761` |
| Batched ground work | 15 | Line 1366 |
| Fine-pitch pass | 7 | Line 1406 |
| Full connectivity | 0 | Line 1463; commit `490d238` follows cleanup |

The first manual passes closed 46 open items; the bulk router pass then closed 134. The initial manual-routing bucket used 28 responses and 18,421 output tokens; the bulk-routing bucket used 11 and 2,458, plus separate router setup/rule repair overhead. These are **not equal tasks**: critical manual paths are deliberately harder and necessary. They support automating ordinary routing earlier, not eliminating engineering attention to power, analog sensing or USB.

The accepted bulk result was reported about 3 minutes 24 seconds after the restored-rule milestone, including a stalled optimizer/restart. Earlier manual routing spanned about 15 minutes 47 seconds from the routing request to its second-pass summary and included compaction. This is an observed timeline, not a general speedup ratio.

## Priorities for reducing repeated work

| Priority | Evidence from this session | Concrete change |
|---|---|---|
| 1. Make routing a reusable operation | Ordinary routing closed 134 open items in one candidate; router setup consumed 17 separate responses | Project-aware export → bounded route → import → refill → native DRC; return file paths, counts and regressions |
| 2. Prepare critical placement and escapes earlier | USB resistors and ESD channel choices were revised after full connectivity; fine-pitch routes were boxed in | Place and protect critical routes and pad escapes before bulk routing; retain targeted final review |
| 3. Verify persisted rules | Line 995 found only the default net class despite documented power/analog classes; fixed in `8d3c7f9` | Save/reopen and assert net-class resolution; inspect DSN constraints before routing |
| 4. Replace environment/API rediscovery | Missing footprint (242), UUID setter failure (472), zone-fill crash (488), relative-project-path assertion (596), Java mismatch (938), missing constants/methods (1284/1505) | Pin versions, run a compact capability probe, store working commands and version adapters |
| 5. Reuse schematic and placement structures | 66 responses and 55,061 output tokens; human found sheets hard to read at line 422 | Parameterized circuit blocks, pin maps and readable layout patterns; inspect one block before expanding |
| 6. Make CI usable before finalization | Placeholder path discovered at 1309, output pipeline repairs at 1366, failed export at 1762, missing expected drill naming at 1893 | Configure and smoke-test the package builder early; test file contents and source provenance |
| 7. Reduce report/context traffic | 719,317 textual tool-output characters; 11 outputs contain a truncation marker | Summaries and DRC deltas by default; full logs, native files, and geometry remain on disk |

The 34 nonzero shell exits are not all avoidable failures: some are searches with no matches, interruptions, or checks correctly rejecting bad candidates. The named errors above were inspected individually. Similarly, textual tool-output characters are a diagnostic size measure, not an estimate of billable tokens; image payloads and repeated context complicate attribution.

The source scripts already contain valuable engineering work. Preserve and parameterize that work rather than asking each new session to rediscover it. In particular, `export_router.py`/`import_router.py`, `check_schematic.py`, and `verify_outputs.py` show useful operations. Their current absolute paths, fixed references, coordinate assumptions and destructive regeneration behavior prevent treating them as a general library unchanged.

## Release provenance finding

The supplied CI summary reports PASS, and its saved DRC/ERC reports contain zero listed violations; saved DRC also has zero unconnected/parity items. However, only **six of seven** recorded source hashes match the supplied files. The `.kicad_pro` hash differs. The later repository diff includes additional ERC and schematic settings. This does not establish a bad board, but the old manifest cannot attest to the exact current project settings. See [the hash comparison](reference_verification.json).

No electrical revalidation or new native CAD check was run for this analysis. The lesson for the reusable release workflow is to check source consistency before and after validation/export, and include custom rules and local libraries in the manifest—not merely stamp current source hashes onto older reports.

## What is ready, and what should be measured next

The [library](../README.md) now contains six concise skills, a reusable session analyzer, a toolchain probe, and a DRC/ERC summarizer with multiset violation deltas. Eight behavioral tests passed, covering duplicate accounting, conflicting records, missing usage, malformed checks, ERC aggregation, equal-count regressions, duplicate violations, and mismatched baselines. All six skills passed the bundled skill validator. The probe and report helper were run against the local environment and supplied reports.

The broader CAD mutation wrappers and circuit-block extraction are an explicitly identified next implementation stage; this first library does not claim they already exist. The [setup guide](../docs/TOOLCHAIN.md) covers prerequisite KiCad/Freerouting components and optional local MCP, InteractiveHtmlBom and KiBot additions. Nothing was installed system-wide.

Use the [controlled replay plan](../docs/NEXT_DESIGN.md) to measure actual savings on the same placement checkpoint. Keep design quality and deliverables fixed, and compare response count, uncached/cached input, output and wall time. A percentage saving cannot be responsibly inferred from this single session.
