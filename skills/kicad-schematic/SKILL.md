---
name: kicad-schematic
description: Create or revise KiCad schematics using reusable circuit blocks, verified pin mappings, and focused electrical and visual checks.
---

Keep circuit intent separate from rendering: a parts table and pin-to-net map should drive any generator and independent exported-netlist checks. Reuse vetted blocks with recorded operating limits, component variants, pin maps, and source datasheet revisions. Reuse a topology only when supply, current, fault behavior, startup state, and accuracy requirements fit the new design.

Prefer an existing maintained generator or editing interface. If extending a native-file generator, preserve UUIDs, references, hierarchical sheet paths, symbol inheritance, and project-local library tables. Generate into a scratch copy first. A construction script that overwrites a board or schematic is not a safe incremental editor.

Arrange each sheet as a readable functional flow before populating all channels. Render one representative block at readable scale, check label collisions, wire junctions, connector meaning, and title-block clearance, then apply the layout pattern. Re-render only changed sheets during iteration; review the full set at handoff.

Run native ERC and compare the exported netlist with the intended pin-to-net map. Verify actual package pad numbering, hidden power/exposed pads, reused pin numbers, and footprint variants. A checker derived solely from the same generator can reproduce its mistake; check critical component pin maps against the manufacturer source.

Record design decisions and unresolved electrical tests once in the project notes. Deliver the schematic, compact ERC/connectivity counts, changed-sheet previews, and outstanding design assumptions. Keep verbose datasheets, netlists, and generated native text out of routine tool responses.
