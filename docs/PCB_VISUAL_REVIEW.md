# Fast iterative PCB review through MCP

Use the existing Dockerized KiCad MCP endpoint. No host KiCad installation, GUI
screenshot script, separate server, or AI-generated board drawing is involved.

PNG is the model's visual input. SVG is the retained vector source for sharp
detail views. IPC inspection and ERC/DRC provide exact engineering evidence.
An image is not a clearance, connectivity, or RF verdict.

## Four functions

| MCP function | Purpose | KiCad export? |
| --- | --- | --- |
| `pcb_visual_review` | Capture a labeled saved-board snapshot; return native PNG images plus metadata | Once per selected view |
| `pcb_visual_history` | Browse/filter/page through retained captures, crops, and comparisons | No |
| `pcb_visual_get` | Retrieve a PNG or retain a higher-resolution detail crop from its SVG | No; crops use only the rasterizer |
| `pcb_visual_compare` | Retain a labeled before/after contact sheet from two captures | No |

Capture, crop, and comparison write artifacts, so their annotations say
non-destructive export, not read-only. None saves, refills, opens, promotes, or
edits a source PCB or the live GUI. History is read-only.

## Short iteration loop

1. Confirm `kicad_get_server_info`, `kicad_get_project_info`, and
   `pcb_get_board_summary`. Explicitly `pcb_save` first if reviewing live edits;
   the renderer does not silently save your work.
2. Call `pcb_visual_review` with a baseline label and retain its `review_id`:

   ```json
   {"label":"placement-baseline","views":["top","bottom","assembly_top"],"width":1600}
   ```

   The response contains native MCP image blocks, not just filenames or SVG text.
3. Make the intended change using the stage's MCP/transaction workflow, save,
   and run `./tools/kicad-docker.ps1 validate <project-stem> --erc --drc`.
4. Capture again with a descriptive label and the same views/width.
5. Call `pcb_visual_compare` with explicit IDs:

   ```json
   {"before_id":"<baseline-id>","after_id":"<new-id>","view":"top"}
   ```

   For finer inspection, call `pcb_visual_get`:

   ```json
   {"review_id":"<new-id>","view":"top","crop":[0.25,0.25,0.5,0.5],"width":2400}
   ```

   This rerasterizes the central half from retained vectors. It does not enlarge
   a low-resolution PNG, export the board again, or lose the original image.
6. Record review IDs/source hashes alongside findings. Never promote a different
   or stale candidate because an earlier image looked good.

Without `crop`, get returns the original PNG immediately. `review_id: "latest"`
means the newest successful capture, never a crop/comparison. Use explicit IDs
for review decisions and concurrent workflows.

You can also pass a crop or comparison ID from history to `pcb_visual_get` to
retrieve that exact saved image without rendering. For these single-image reviews,
`view` and `width` are ignored; use the original capture ID to request a new crop.

## Capture arguments and views

| Argument | Default | Meaning |
| --- | --- | --- |
| `board_path` | active saved board | Absolute container path or unambiguously workspace-relative path |
| `label` | empty | Review note, at most 240 characters |
| `views` | `["top","bottom"]` | Named views below; exactly `["all"]` selects all six |
| `width` | `1600` | PNG width, 400–6000px; also capped at 6000px height and 16 megapixels |
| `layers` | unset | Custom canonical layer list; mutually exclusive with `views` |
| `mirror` | `false` | Custom-layer orientation only |
| `expected_sha256` | unset | Require these exact saved PCB bytes before capture |
| `include_images` | `true` | False skips inline transfer but still saves every image |

| View | Layers | Orientation |
| --- | --- | --- |
| `top` | F.Cu, F.SilkS, Edge.Cuts | Top |
| `bottom` | B.Cu, B.SilkS, Edge.Cuts | Mirrored, viewed from underside |
| `assembly_top` | F.Fab, F.CrtYd, F.SilkS, Edge.Cuts | Top |
| `assembly_bottom` | B.Fab, B.CrtYd, B.SilkS, Edge.Cuts | Mirrored |
| `copper_top` | F.Cu, Edge.Cuts | Top |
| `copper_bottom` | B.Cu, Edge.Cuts | Mirrored |

Defaults exclude solder mask to keep copper legible. Request mask, paste, or
inner layers explicitly, e.g. `{"layers":["In1.Cu","Edge.Cuts"],"label":"inner-plane"}`.
That capture's view name is `custom`. Inspect the board's actual layers first;
an absent layer cannot reveal nonexistent geometry.

Rendering uses an isolated KiCad default palette and dark background so white
silkscreen stays visible. A 2mm viewport margin keeps the outline and nearby
connector labels visible; untouched native SVGs are retained separately.
Crops are normalized display coordinates
`[left,top,width,height]`, within [0,1], not millimeters. Bottom coordinates
follow the mirrored image. The fitted SVG viewBox does not establish absolute
PCB coordinates; use IPC pad/footprint data for measurements.

`pcb_visual_compare(before_id, after_id="latest", view="top", label="", width=2400)`
checks equal layers/orientation and warns about different render settings.
Images are independently fitted side-by-side. This is not a registered pixel
difference, improvement score, or electrical verdict. Retrieve originals/crops
for subtle changes.

## Isolated placement/routing candidates

Keep the live project selected. Send the actual candidate path and SHA-256 from
the job result to `pcb_visual_review`:

```json
{
  "board_path":".kicad-automation/routing/<job-id>/<actual-candidate>.kicad_pcb",
  "expected_sha256":"<candidate-sha256-from-job-result>",
  "label":"candidate-<job-id>",
  "views":["top","bottom","assembly_top"]
}
```

Do not guess candidate directory layouts. The runtime explicitly sets
`KICAD_MCP_WORKSPACE_ROOT=/workspace`, allowing candidates elsewhere in the mounted
repository. Windows host paths, traversal, and paths/symlinks outside the workspace
are rejected. Candidate captures go into the active project's history. Do not
switch/open/promote a board merely to view it.

The source PCB and matching `.kicad_pro` settings/text variables are copied and
hashed before export. All selected views render the same frozen copies.
`source.sha256` identifies the PCB; companion hashes are in `artifacts`.
If either original changes during capture, `source.changed_during_capture` and
`warnings` report it. Those images describe the frozen snapshot, not the newest
board: recapture before approval. Unsaved GUI changes are not inspected/included.

Promotion still requires the documented transaction adapter, source/candidate
hash checks, supported-change checks, verified save/reopen/readback, and
post-mutation validation. Rendering never promotes a candidate.

## Retention and progress browsing

Each accepted capture, crop, and comparison gets a unique UTC/label/random ID:

```text
<active-project>/output/image-review/
  index.html                       derived gallery, newest first
  <capture-id>/
    manifest.json                  source hashes, versions, errors, paths
    review.html
    source/<stem>.kicad_pcb         exact captured bytes
    source/<stem>.kicad_pro         when present
    top.raw.svg                    untouched native KiCad export
    top.svg                        same geometry, explicit background
    top.png
    ...                            other views and isolated render config
  <crop-id>/                        detail.svg, detail.png, manifest, report
  <comparison-id>/                  comparison.png, manifest, report
```

Nothing automatically prunes or replaces earlier runs, even for identical boards.
Partial/failed exports and journals are retained. Interrupted processes can leave
a `running` journal; that is not success. Only a current run's journal and the
derived gallery index are updated. Legacy folders/images remain untouched and
are reported as skipped if they lack a v2 manifest.

Open the returned `gallery` path locally to see progress. Metadata paths are
relative to `/workspace`, the mounted host repository. The HTML works directly
from disk without a web server, scripts, or cloud upload.

`pcb_visual_history` returns metadata without images:

```json
{"limit":10,"label":"placement","kind":"capture"}
```

Filters are optional; kind is capture/crop/comparison. Pass `next_before_id` back
as `before_id` for stable newest-first pagination. Limit is 1–100. Artifact hashes
are verified on retrieval; changed files are rejected.

Inline PNGs have a 12 MiB per-response budget. On overflow, metadata still points
to all saved images and suggests requesting one view at a time. Prefer 1600px
overviews and targeted 2400px crops over repeatedly transmitting six large views.

History grows on disk intentionally. It is excluded from Git/Docker build context
by default, not deleted. Back up/archive it with the project, or force-add selected
evidence to Git when required.

## Build, discover, and verify

This is a context-checked patch to pinned `kicad-mcp-pro==3.34.0`, not an unversioned
runtime monkey patch. The image includes KiCad 10.0.4, `rsvg-convert` from the
digest-pinned base, and Pillow 12.3.0. Builder/review profiles and the project MCP
allowlist include all four functions.

```powershell
./tools/kicad-docker.ps1 build
./tools/kicad-docker.ps1 test
```

Build checks cover actual registration, schemas, annotations, capabilities,
profile routing, and core regressions. The isolated integration suite uses real
HTTP MCP and native rendering. It checks repeatable unchanged-state PNGs,
retrieval/cropping/comparison, previous-image retention, source immutability,
path/digest errors, live IPC save/readback, and clean fixture ERC/DRC.

Rebuilding does not replace a running container. Recreate the service with the
intended board only after live edits have been explicitly saved or secured:

```powershell
./tools/kicad-docker.ps1 up esp32_sensor_board/esp32_sensor_board
```

Refresh/reconnect the MCP client afterwards to update its cached catalog. The
repository client can query the actual running server immediately:

```powershell
python ./scripts/kicad_mcp_client.py schema pcb_visual_review
python ./scripts/kicad_mcp_client.py call pcb_visual_history
```

For PowerShell-safe JSON, use a JSON file and `--arguments '@path/to/arguments.json'`.
The CLI prints image blocks as base64; prefer native MCP calls for vision or open
the retained PNG instead of flooding a text terminal with image data.

Render-only regression inside the image with its MCP server running:

```sh
python3 /workspace/tests/integration_visual_review.py \
  --board /workspace/tests/fixtures/kicad-project/minimal.kicad_pcb
```

For missing tools, inspect the actual `schema` endpoint, not a synthetic catalog;
an old container still has old tools after a build. For render failures, inspect
the run's manifest and retained raw SVG. Missing renderers, timeouts, and partial
exports are errors, never replaced by a screenshot or invented board drawing.

References: [KiCad 10 CLI SVG export](https://docs.kicad.org/10.0/en/cli/cli.html)
and [MCP image/structured tool results](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).
