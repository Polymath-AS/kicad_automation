# PCB image review workflow

See [the repository's complete MCP review guide](../../docs/PCB_VISUAL_REVIEW.md).
Use `pcb_visual_history` to find earlier review IDs, `pcb_visual_get` for sharp
detail crops from saved vectors, and `pcb_visual_compare` for before/after sheets.
Open [the retained history gallery](../output/image-review/index.html)
to browse retained images. Explicitly save before capturing live edits. For
candidates, use their actual path and `expected_sha256` from the job result.

Use the MCP visual-review tool before promoting an autoplacement or autorouting candidate:

```powershell
python .\scripts\kicad_mcp_client.py call pcb_visual_review `
  --arguments '{"label":"placement-review","views":["top","bottom","assembly_top"]}'
```

For an isolated routing candidate, pass the candidate board path instead:

```powershell
python .\scripts\kicad_mcp_client.py call pcb_visual_review `
  --arguments '@path/to/candidate-review-arguments.json'
```

Use the candidate path and SHA-256 from the job result in that JSON file; do not
guess its directory layout. Native MCP calls are preferred for inline model vision.

The tool runs the pinned KiCad CLI against a frozen copy of the saved board and does not open or mutate the live
editor. Every call creates a unique timestamped/labeled directory under
`output/image-review/`; existing SVG and PNG artifacts are retained. The PNGs are returned directly
through MCP for model vision, while the SVGs preserve exact vector geometry for later inspection.

Review every candidate for:

- connector and board-edge constraints;
- ESP32 antenna keepout and copper approach direction;
- local decoupling placement and thermal separation;
- USB differential-pair geometry and short return paths;
- routing congestion, accidental long detours, and component courtyard crowding;
- traces that technically connect but make assembly, probing, or rework worse.

Promotion still requires candidate/source digest checks, no new non-connectivity, acceptable
clearance/via geometry, IPC promotion, save/readback, and ERC/DRC validation. A visually
poor candidate is rejected even if its router summary says it succeeded.
