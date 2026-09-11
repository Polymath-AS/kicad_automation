"""Build-time regression checks for local, version-pinned MCP compatibility patches."""

from types import SimpleNamespace
from pathlib import Path
import tempfile
import asyncio

from kicad_mcp.tools import pcb_visual_review, routing
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

assert list(pcb_visual_review.VIEW_SPECS) == [
    "top", "bottom", "assembly_top", "assembly_bottom", "copper_top", "copper_bottom"
]
assert pcb_visual_review.DEFAULT_VIEWS == ("top", "bottom")

# Verify real server registration, public schemas and mode/capability routing.
# Compilation/constants alone cannot detect a tool silently filtered out of MCP.
from kicad_mcp import capabilities
from kicad_mcp.server import KiCadFastMCP
from kicad_mcp.tools.router import TOOL_CATEGORIES, PROFILE_TOOL_ALLOWLISTS
from kicad_mcp.operating_modes import is_tool_allowed_in_mode

visual_names = {
    "pcb_visual_review", "pcb_visual_history", "pcb_visual_get", "pcb_visual_compare"
}
server = KiCadFastMCP("visual-review-build-check")
pcb_visual_review.register(server)
schemas = {t.name: t for t in asyncio.run(server.list_tools())}
assert visual_names <= schemas.keys(), schemas.keys()
assert visual_names <= set(TOOL_CATEGORIES["pcb_read"]["tools"])
assert visual_names <= set(PROFILE_TOOL_ALLOWLISTS["review"])
assert schemas["pcb_visual_history"].annotations.readOnlyHint
for name in visual_names - {"pcb_visual_history"}:
    assert not schemas[name].annotations.readOnlyHint
    assert not schemas[name].annotations.destructiveHint
    assert capabilities.get(name).writes_files
    assert not capabilities.get(name).writes_kicad_gui_state
    assert is_tool_allowed_in_mode(name, "write")
assert "expected_sha256" in schemas["pcb_visual_review"].inputSchema["properties"]
assert "crop" in schemas["pcb_visual_get"].inputSchema["properties"]
assert "before_id" in schemas["pcb_visual_compare"].inputSchema["required"]

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
