# MCP-First Design Workflow

1. Start the Docker runtime against the target board under `/workspace`.
2. Connect Codex to `http://127.0.0.1:3334/mcp`.
3. Call `kicad_get_server_info`, `kicad_get_project_info`, and `kicad_get_version` before editing.
4. Inspect PCB state with MCP Pro tools such as `pcb_get_board_summary`, `pcb_get_footprints`, `pcb_get_nets`, `pcb_get_tracks`, and `pcb_get_shapes`.
5. Apply the initial placement with IPC-backed MCP Pro tools, save it, then run the conservative
   KiCadRoutingTools `placement` candidate stage to improve routability before copper. Lock
   connectors, mounting parts, and RF/mechanical-critical parts and supply reviewed intent.
6. Prefer the isolated KiCadRoutingTools `planes`/`diff`/`route` candidate workflow for routing;
   use `pcb_route_trace` for reviewed small fixes or explicit fallback only.
7. Promote reviewed candidates only through the routing/placement transaction adapters; require
   stale-source checks, save/reopen/readback, and explicit rollback status.
8. Save direct IPC edits with `pcb_save`.
9. Run `validate-kicad --erc --drc` through Docker after each meaningful automated change.
10. Use `validate-kicad --gerbers --drill --pdf` and the bundled `kicad10_auto` tools only from a saved design state that passed validation or has documented accepted violations.

Schematic work in KiCad 10 is deliberately explicit. Prefer MCP Pro schematic tools. Where MCP Pro uses direct S-expression manipulation, treat that as a visible file-backed operation and validate immediately with `kicad-cli sch erc`.

Do not reintroduce a repo-owned PCB file-writing backend to bypass IPC. If KiCad 10 IPC or MCP Pro lacks a PCB capability, expose that as unsupported and decide whether the operation belongs upstream or in a future narrow adapter.
