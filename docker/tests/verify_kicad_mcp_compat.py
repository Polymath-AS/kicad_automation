"""Build-time regression checks for local, version-pinned MCP compatibility patches."""

from types import SimpleNamespace
from pathlib import Path
import tempfile

from kicad_mcp.tools import routing
from kicad_mcp.utils.layers import resolve_layer_name


pad = SimpleNamespace(number="7")
footprint = SimpleNamespace(
    reference_field=SimpleNamespace(text=SimpleNamespace(value="U1")),
    definition=SimpleNamespace(pads=[pad]),
)

routing.get_board = lambda: object()
routing.board_footprints = lambda _board: [footprint]

assert routing._find_pad("U1", "7") is pad
assert routing._find_pad("U1", "8") is None
assert routing._find_pad("U2", "7") is None

assert resolve_layer_name("F.Cu") == "F_Cu"
assert resolve_layer_name("F_Cu") == "F_Cu"
assert resolve_layer_name("BL_F_Cu") == "F_Cu"
assert resolve_layer_name("BL_Edge_Cuts") == "Edge_Cuts"

with tempfile.TemporaryDirectory() as directory:
    import kicad_mcp.tools.pcb as pcb
    original_footprint_file = pcb._footprint_file
    pcb._footprint_file = lambda _library, _name: Path(directory) / "fixture.kicad_mod"
    try:
        (Path(directory) / "fixture.kicad_mod").write_text(
            '(footprint "PinHeader_1x01" (layer "F.Cu") '
            '(property "Reference" "REF**") (property "Value" "Conn"))',
            encoding="utf-8",
        )
        rendered = pcb._render_board_footprint_block(
            "Connector:PinHeader_1x01", reference="J1", value="Conn",
            x_mm=1.0, y_mm=2.0, rotation=0, pad_nets={},
        )
        assert rendered.startswith('(footprint "Connector:PinHeader_1x01"')
    finally:
        pcb._footprint_file = original_footprint_file
