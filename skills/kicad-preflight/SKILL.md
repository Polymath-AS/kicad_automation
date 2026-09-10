---
name: kicad-preflight
description: Verify the Dockerized KiCad 10 IPC runtime before PCB edits, schematic inspection, or manufacturing exports.
---

Start from the Docker runtime, not a host KiCad installation. Run the full container integration
test after runtime/image changes or before release; routine design sessions need live readiness and
target-project checks, not an unconditional rebuild.

Required checks: `kicad_get_server_info` reports KiCad 10.x with live PCB IPC,
`kicad_get_project_info` resolves the intended project under `/workspace`,
`pcb_get_board_summary` succeeds from `live-gui`, and the saved design can be checked with
`.\tools\kicad-docker.ps1 validate <project-stem> --erc --drc`. For runtime diagnostics, also
verify Xvfb, pcbnew, `/runtime/tmp/kicad/api.sock`, and MCP initialization at `/mcp`.

Confirm the mounted project path is under `/workspace`. Runtime state belongs under `/runtime`, KiCad config under `/config`, and caches under `/cache`. Do not use hidden source copies as the normal workflow.

If IPC is unavailable, diagnose Xvfb, KiCad startup, `api.enable_server`, socket creation, or `kicad-python` connection errors. Do not switch to SWIG `pcbnew`.

Return a compact readiness report: image version, opened board, IPC state, MCP endpoint, validation
result/report path, routing-service availability when needed, and any unsupported operation.
