---
name: kicad-schematic
description: Inspect or revise KiCad schematics with KiCad 10 IPC where available, otherwise explicit structured file manipulation plus kicad-cli ERC.
---

KiCad 10 schematic IPC coverage is limited. Use MCP Pro schematic tools such as `sch_get_symbols`, `sch_get_wires`, `sch_get_labels`, `sch_get_connectivity_graph`, and `sch_visual_qa` for inspection. Do not claim mutable schematic IPC support unless the specific operation is implemented and tested.

For schematic mutation, prefer MCP Pro operations that already perform scoped structured S-expression edits and validation. New local mutation code should be added only when MCP Pro and KiCad IPC both lack the capability, and it must preserve unrelated data, update only intended nodes, and immediately validate with `kicad-cli sch erc`.

Do not use regex replacement for KiCad S-expressions. Do not retain or call a generic schematic generator as a fallback.

Return changed-sheet paths, ERC result paths, and unsupported capabilities explicitly.
