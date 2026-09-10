# Differential-routing fixture

Generated through the live KiCad 10.0.4 MCP builder and synchronization path.
J1 and J2 are genuine four-pin connector symbols with `USB_D_P`/`USB_D_N`
paired by the pinned KiCadRoutingTools `_P`/`_N` net convention.  The fixture
also carries GND and VCC nets so the differential operation is not two unrelated
unconnected copper names.  The checked-in source contains no tracks; the
candidate route must preserve both net names and survive save/readback.

Run `routing-plans/krt-diff.json` with the optional routing image.  The two
footprint-symbol mismatch warnings are the known upstream synchronization
diagnostic and are intentionally not excluded.
