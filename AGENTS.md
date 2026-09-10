# KiCad Automation Workflow

This repository is operated through the Dockerized KiCad 10 MCP server.

## Electrical design process

For new electrical designs or substantial redesigns, load `ee-design` first.

`ee-design` owns design intent, component selection, and progression through schematic, placement, routing, and review.

Prefer engineering judgment, research, and explicit assumptions over asking the user for every unspecified parameter. Ask only when a missing decision materially changes the intended product.

Use the relevant `kicad-*` skill to execute each stage.

## Required project layout

  Every new electrical project or substantial redesign MUST use this structure:

  <project>/
  ├── <project>.kicad_pro
  ├── <project>.kicad_sch
  ├── <project>.kicad_pcb
  └── design/
      └── ee-state.yaml

  Rules:

  - `<project>` is the project root and the filename stem must match the directory name.
  - Use `kicad_create_new_project` for the three KiCad files.
  - Create `design/ee-state.yaml` from `skills/ee-design/templates/ee-state.yaml`.
  - Create and initialize `ee-state.yaml` before modifying the schematic or PCB.
  - Update `ee-state.yaml` as the design progresses through its stages.
  - Do not place the state file beside the KiCad files.
  - Before reporting success, verify that all five required paths exist.

## EDA tasks

For any PCB or KiCad project request:

1. Confirm the live connection with `kicad_get_server_info`.
2. Query `kicad_get_project_info` and `pcb_get_board_summary` before editing.
3. Use MCP Pro IPC-backed PCB tools for inspection, initial placement, candidate promotion, and saving.
4. After initial component placement and before adding copper, prefer the isolated
   KiCadRoutingTools `place_optimize` candidate stage to improve routability. Lock connectors,
   mounting parts, and RF/mechanical-critical parts; pass a reviewed placement intent when one
   exists. Use `move_refs` when only a selected component subset may move; use `mode: reseat`
   with intent when that subset must be placed again from scratch. Review and promote only a
   candidate that preserves the hard placement constraints.
5. Prefer KiCadRoutingTools candidate jobs for board routing (`planes`, `diff`, then `route` as
   applicable). Use `routing_plan_trace`/`pcb_route_trace` only for previews, small manual fixes,
   or when the candidate router cannot handle the requested edit; do not silently fall back.
6. Use `kicad_create_new_project` for new projects instead of hand-writing KiCad files.
7. Run the repository validation command after every design mutation:
   `.\tools\kicad-docker.ps1 validate <project-stem> --erc --drc`.

For new electrical designs or substantial redesigns, load `ee-design` first.
Then load the repository skill matching the current execution stage:
`kicad-preflight`, `kicad-schematic`, `kicad-placement`,
`kicad-autoroute`, `kicad-drc`, or `kicad-release`. Routing and placement
promotion must use the reviewed transaction adapters documented by those skills. Fail closed on
unsupported copper removals/vias, stale source digests, or unverified rollback; never represent a
partial or recovery-required result as success.

Do not begin an EDA task with a broad scan of `references/`, historical analysis, or unrelated
helpers. Read only the target project and the tool documentation needed for the requested action.

Do not mutate `.kicad_pcb` or `.kicad_pro` files directly when an MCP operation exists. Do not use
`pcbnew` SWIG bindings, invent unsupported tool calls, or silently replace a failed IPC operation
with file edits. If the MCP server is unavailable, diagnose the connection and stop before making
design changes.

## New project bootstrap

Create the project as a complete directory containing `.kicad_pro`, `.kicad_sch`, and `.kicad_pcb`.
The runtime needs an existing board to establish its initial IPC document; create a new project
while the service is running against the fixture or another existing board, then restart the
service with the generated board as its target.

## Completion criteria

For a test PCB, report the live server state, board summary, files created or changed, save and
reopen/readback result, and ERC/DRC result. For candidate workflows also report source/candidate
hashes, promotion status, and rollback/recovery state. Prefer a small deterministic test design
over scanning unrelated examples.
