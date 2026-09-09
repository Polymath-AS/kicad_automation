"""Build-time regression checks for local, version-pinned MCP compatibility patches."""

from types import SimpleNamespace

from kicad_mcp.tools import routing


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
