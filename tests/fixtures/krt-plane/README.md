# Plane/power-routing fixture

Generated through the live KiCad 10.0.4 MCP builder and synchronization path.
The two four-pin connectors share a real `GND` power net plus VCC and the USB
differential pair.  The plane plan creates a B.Cu GND zone with explicit
clearance and power width controls; it is checked independently from the
differential plan so a plane operation cannot silently route unrelated nets.

Run `routing-plans/krt-plane.json` with the optional routing image.  The source
triplet is never overwritten by candidate jobs.
