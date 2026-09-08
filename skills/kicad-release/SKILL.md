---
name: kicad-release
description: Generate and verify KiCad manufacturing and review outputs with kicad-cli from the Dockerized KiCad 10 runtime.
---

Use `validate-kicad` or MCP Pro commands such as `run_erc`, `run_drc`, `export_gerber`, `export_drill`, `export_pcb_pdf`, `export_sch_pdf`, and `export_manufacturing_package`. `kicad-cli` is the authority for checks and exports.

Run checks against the saved design state after IPC edits. A nonzero ERC/DRC result, malformed JSON report, missing artifact, or kicad-cli tool error fails the release unless explicitly accepted by the project owner.

Keep generated outputs under `/runtime` by default or under a project-requested artifact directory. Do not let KiCad runtime locks, caches, or logs pollute the source tree.

Report source paths, KiCad version, validation result paths, export directories, and remaining limitations. KiBot, iBOM, KiKit, and related bundled tools are available from the pinned `kicad10_auto` image, but normal release checks still flow through MCP Pro or the `validate-kicad` wrapper.
