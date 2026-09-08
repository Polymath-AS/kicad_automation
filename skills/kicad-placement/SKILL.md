---
name: kicad-placement
description: Place KiCad PCB functional groups and prepare critical routing paths and mechanical constraints before bulk autorouting.
---

Read the circuit intent, mechanical envelope, connector access, and fabrication constraints. Place connectors, mounting features, antenna keepouts, and heat sources first. Then place circuit groups with their local support components. Use actual pad/courtyard geometry and orientations, not body centers alone.

Prepare critical topology before bulk routing: switching-current loops, decoupling returns, Kelvin sensing, sensitive analog paths, differential pairs, and their return paths. Place USB ESD channels and series resistors so the intended pair geometry is achievable. Inspect fine-pitch pad escapes and reserve via space before ordinary traces box them in. Select dimensions from this design's rules; never copy the example board's numeric defaults blindly.

Use parameterized placement tables or group transforms for repeated blocks. Make one coherent group edit, refill where relevant, and check clearance/courtyard/edge/schematic parity together. Treat unrouted items as expected during placement, but report them separately from physical violations. A draft with zero clearance violations is not a finished board.

Save a placement checkpoint with a compact group map, routing priorities, reserved layers, and unresolved mechanical issues. Inspect one overview and focused crops of crowded areas. Reuse these artifacts until geometry changes instead of regenerating a full documentation package after each edit.
