# KiCad Automation Workflow

This repository is operated through the Dockerized KiCad 10 MCP server.

## EDA tasks

For any PCB or KiCad project request:

1. Confirm the live connection with `kicad_get_server_info`.
2. Query `kicad_get_project_info` and `pcb_get_board_summary` before editing.
3. Use MCP Pro IPC-backed PCB tools for inspection, placement, routing, and saving.
4. Use `kicad_create_new_project` for new projects instead of hand-writing KiCad files.
5. Run the repository validation command after every design mutation:
   `.\tools\kicad-docker.ps1 validate <project-stem> --erc --drc`.

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

For a test PCB, report the live server state, board summary, files created or changed, save result,
and ERC/DRC result. Prefer a small deterministic test design over scanning unrelated examples.
