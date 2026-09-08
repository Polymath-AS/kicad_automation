---
name: kicad-preflight
description: Verify a KiCad automation environment and saved project rules before PCB generation, routing, or manufacturing exports.
---

Establish the toolchain once per project or version change. Run this skill's `scripts/probe_toolchain.py --help`, then probe explicit executable paths and save its JSON outside the design sources. The probe reports capabilities; a discovered JAR is not a tested router.

Use `kicad-cli` for ERC/DRC and exports. For existing `pcbnew` scripts, use Python bundled with the same KiCad installation. Do not rediscover methods with repeated `dir()` dumps: run a small capability probe and retain the successful invocation. New GUI integration can use the official IPC API; check its version-specific coverage before replacing working headless scripts.

Load the saved `.kicad_pro` before the board in a legacy `pcbnew` worker. Verify persisted net classes, net-to-class assignments, layer permissions, track/via dimensions, and fabrication constraints against the design intent. Save, unload, reopen, and check these again after changing rules. Check the exported DSN too; documented rules and in-memory settings are insufficient evidence.

Verify symbol, footprint, and requested 3D library paths with representative assets. Resolve the exact Java executable and router version; do a DSN-to-SES smoke run on a scratch board before production routing. Record the working command and limits. Keep long logs on disk.

Configure the existing output entry point before layout starts. Check it rejects a deliberately invalid scratch design and includes all intended copper and drill outputs. Distinguish missing dependencies from design violations.

Return a short readiness report: versions, missing capabilities, saved-rule mismatches, and the next concrete fix. Store paths, versions, successful commands, and known compatibility limitations in the project's toolchain record.
