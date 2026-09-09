"""Build-time regression checks for local, version-pinned MCP compatibility patches."""

from types import SimpleNamespace

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
