# Routing fixture

Created with the live KiCad 10 MCP tools, not hand-written PCB geometry. Two through-hole
single-pin headers at (30, 30) and (50, 30) mm share the SIGNAL net. Saved source has no copper.

Baseline: ERC 0; DRC one unconnected item and two footprint-symbol mismatch warnings.
The warnings expose MCP schematic sync dropping library-qualified footprint IDs; do not suppress
them merely to obtain a green test. Routing should remove the unconnected item without adding
findings, return `needs_review`, and leave this source triplet unchanged.

Run `routing-plans/smoke.json` through the optional routing service. See
`docs/KICAD_ROUTING_TOOLS.md` for evidence, reproduction and limitations. The diagnostic
`scripts/build_routing_fixture.py` documents creation; normal tests use this saved fixture.
