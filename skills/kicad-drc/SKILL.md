---
name: kicad-drc
description: Diagnose KiCad ERC/DRC reports with compact counts and violation deltas, then verify focused PCB fixes without weakening design constraints.
---

Run native checks against the current saved candidate, with project rules loaded and zones freshly filled. For CLI versions supporting these flags, use `pcb drc --format json --schematic-parity --severity-all --exit-code-violations --output REPORT BOARD`; use `sch erc` with the corresponding JSON/severity/exit flags for schematics. Exit code 5 means reported violations; other failures are tool failures, not a clean check.

Summarize JSON using this skill's `scripts/summarize_checks.py REPORT --baseline PREVIOUS_REPORT --limit 5`. Omit the baseline on the first pass. The helper accepts native DRC or ERC JSON, reports counts by category/type/severity, and preserves duplicate violations when computing added/resolved counts. It does not rerun checks or establish report freshness.

Keep full reports on disk; load only the representative failures and relevant coordinates/items. Group fixes by cause and physical region: pad escape, plane access, clearance, footprint mismatch, silkscreen, or dangling copper. Make a coherent batch and rerun. Compare fingerprints as well as counts: one resolved violation can hide a different new violation.

Maintain separate counts for rule violations, unrouted items, and schematic parity. During routing, open items are expected; at completion, require closure and no unaccepted violations. Preserve valid rules and record any justified exception explicitly. Never globally suppress a rule category to hide a local geometry problem.

If a repeated edit fails to improve the candidate, inspect the local geometry or constraint interpretation before continuing the same edit loop. Review critical electrical behavior separately: DRC establishes geometric consistency, not circuit correctness, impedance, thermal margin, or manufacturability under an unspecified stackup.
