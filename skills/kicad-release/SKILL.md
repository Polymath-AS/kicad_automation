---
name: kicad-release
description: Generate and verify a KiCad manufacturing and review package with current ERC/DRC results, complete outputs, and source provenance.
---

Use the project's established output entry point; configure a reusable exporter if none exists. Run a lightweight check after relevant edits and the complete export at a stable release milestone. Avoid repeatedly generating STEP, renders, and all PDFs during trace cleanup.

Take source hashes before checks/exports and verify them afterwards. Include the PCB, all schematic sheets, project settings, custom rules, and project-local symbol/footprint libraries. If a GUI or exporter changes a source, determine whether checks/outputs need rerunning and produce a consistent new manifest. Do not attach current hashes to old reports and imply they were checked together.

Require current native ERC, DRC, unrouted-item and schematic-parity results plus critical pin/net checks. A missing report, nonzero tool failure, stale output, or malformed JSON fails validation. Handle accepted exceptions explicitly rather than hiding them in a zero count.

Export the requested copper layers, masks, silkscreens, board outline, paste where applicable, plated/nonplated drill files, BOM, and placement data. Generate requested schematic/board PDFs and 3D views once. Confirm actual ZIP members, layer coverage, drills, BOM quantities/variants, DNP treatment, position origin/rotation convention, and reference consistency. Inspect rendered drawings for clipping and readable labels. If rendering is unavailable, report the missing visual check rather than declaring it passed.

Keep fabrication stackup/impedance requirements and bench tests distinct from CAD results. Produce one release manifest with input hashes, tool versions, command outcomes, report paths, artifact hashes, and unresolved limitations. Update the project status and create a milestone commit when that is part of the authorized workflow.
