---
name: kicad-placement
description: Place or refine KiCad PCB footprints using live KiCad IPC, constrained KiCadRoutingTools candidates, and verified promotion/readback.
---

Inspect the live board with MCP Pro tools such as `pcb_get_board_summary`, `pcb_get_footprints`, `pcb_get_nets`, `pcb_get_tracks`, `pcb_get_vias`, and `pcb_get_shapes`. Use actual footprint references and pad/net context returned by the tool output.

Apply initial or small reviewed edits with `pcb_move_component` or `pcb_move_footprint`. Before
copper, prefer a bounded KiCadRoutingTools `placement` candidate for routability refinement. Lock
connectors, mounting hardware, RF/mechanical-critical parts, and all parts outside `move_refs`;
require reviewed intent for reseat mode. Do not edit `.kicad_pcb` directly.

Promote reviewed candidates through `scripts/kicad_live_placement.py` and the transaction contract
in `scripts/kicad_placement.py`. Require a current source digest, hard-constraint pass, `pcb_save`,
reopen/readback verification, and explicit rollback reporting. A partial or recovery-required result
is not success.

After each coherent placement mutation, run `run_drc` and `run_erc` through MCP Pro or the
repository validator. Treat `kicad-cli` as authoritative. Full reports persist under
`.kicad-automation/reports`; load only focused details into the conversation.

If KiCad IPC rejects an update, report the failing IPC operation and leave the design unmodified. Do not retry through SWIG or a private file mutation path.
