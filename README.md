# KiCad automation skill library

An initial reusable library built from the 2026-09-07 ESP32 / 24 V / 4-20 mA design session. The main opportunity is to replace repeated geometry/debugging conversations with verified tool operations and concise results.

- [Session findings and priorities](analysis/SESSION_ANALYSIS.md)
- [Tools and KiCad plugins to prepare](docs/TOOLCHAIN.md)
- [Turnkey Docker toolchain](docs/DOCKER_TOOLCHAIN.md)
- [Next-design workflow and measurement plan](docs/NEXT_DESIGN.md)

| Skill | Purpose |
|---|---|
| [kicad-preflight](skills/kicad-preflight/SKILL.md) | Verify executable paths, APIs, saved rules, and export readiness |
| [kicad-schematic](skills/kicad-schematic/SKILL.md) | Reuse circuit blocks, pin maps, and readable sheet layouts |
| [kicad-placement](skills/kicad-placement/SKILL.md) | Arrange groups, critical paths, and pad escapes before routing |
| [kicad-autoroute](skills/kicad-autoroute/SKILL.md) | Bulk routing with protected copper and native KiCad acceptance checks |
| [kicad-drc](skills/kicad-drc/SKILL.md) | Compact report summaries and added/resolved violation counts |
| [kicad-release](skills/kicad-release/SKILL.md) | Consistent source provenance and complete manufacturing outputs |

These are library source folders. To enable them for another design, copy the desired complete skill folders into that repository's `.agents/skills/`, then reopen the session and confirm discovery. Do not paste all skill bodies into `AGENTS.md`: load the relevant skill as work changes phase. The current [official discovery documentation](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills) describes repository-local skill scanning.

No system-wide skills or KiCad plugins were installed as part of this analysis. The reference design is retained as evidence. Its construction scripts are checkpoint-dependent and can overwrite later design work; they are not a general-purpose replay pipeline.

## Reproduce the analysis

From this repository in PowerShell:

```powershell
python tools/analyze_session.py references/rollout-2026-09-07T10-46-19-01a07b0c-0257-74a1-a03d-98d563f35507.jsonl --phases analysis/phases.json --out analysis/session
python -m unittest discover -s tests -v
```

The analyzer uses the Python standard library. It writes usage, message, and command ledgers plus a compact summary. For a different session, omit `--phases` or supply boundaries appropriate to that session. Generated command/message ledgers can contain project details from the source; review before sharing them outside your workspace.

The two executable skill helpers are a toolchain probe and a DRC/ERC summarizer. Autorouting, schematic generation, and release skills currently specify the workflow and acceptance contract; they do not yet provide a fully parameterized CAD mutation engine. The extraction priorities and a benchmark to validate actual savings are in the linked reports.
