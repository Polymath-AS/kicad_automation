---
name: kicad-preflight
description: Verify the Dockerized KiCad 10 IPC runtime before PCB edits, schematic inspection, or manufacturing exports.
---

Start from the Docker runtime, not a host KiCad installation. Build the image, then run `docker compose run --rm test` before using a project for automated edits.

Required checks: KiCad reports 10.x, Xvfb accepts `DISPLAY=:99`, pcbnew launches with the target board, `/runtime/tmp/kicad/api.sock` exists, MCP Pro initializes at `/mcp`, `kicad_get_server_info` reports live IPC, an IPC-required PCB query such as `pcb_get_shapes` succeeds, and `validate-kicad --erc --drc` runs through `kicad-cli`.

Confirm the mounted project path is under `/workspace`. Runtime state belongs under `/runtime`, KiCad config under `/config`, and caches under `/cache`. Do not use hidden source copies as the normal workflow.

If IPC is unavailable, diagnose Xvfb, KiCad startup, `api.enable_server`, socket creation, or `kicad-python` connection errors. Do not switch to SWIG `pcbnew`.

Return a compact readiness report: image version, opened board, IPC socket, MCP Pro endpoint, validation command, and any unsupported operation discovered.
