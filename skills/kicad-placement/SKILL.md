---
name: kicad-placement
description: Place KiCad PCB functional groups through the KiCad 10 IPC tool surface and verify edits with kicad-cli.
---

Inspect the live board with MCP Pro tools such as `pcb_get_board_summary`, `pcb_get_footprints`, `pcb_get_nets`, `pcb_get_tracks`, `pcb_get_vias`, and `pcb_get_shapes`. Use actual footprint references and pad/net context returned by the tool output.

Apply placement edits with `pcb_move_component` or `pcb_move_footprint`. Save with `pcb_save`; do not edit `.kicad_pcb` directly for placement.

After each coherent placement batch, run `run_drc` and `run_erc` through MCP Pro or `validate-kicad`. Treat kicad-cli as authoritative for violations and parity. Keep full reports in `/runtime/reports` and load only focused details into the conversation.

If KiCad IPC rejects an update, report the failing IPC operation and leave the design unmodified. Do not retry through SWIG or a private file mutation path.
