import json
import unittest

from scripts.kicad_live_adapter import McpLiveAdapter, parse_pin_positions, parse_schematic_symbols
from scripts.kicad_live_promotion import parse_live_tracks, parse_live_vias
from scripts.kicad_contracts import DrcExclusionFilter


def response(text, *, error=False):
    return {"result": {"content": [{"text": text}], "structuredContent": {"result": text},
                        "isError": error}}


class LiveAdapterTests(unittest.TestCase):
    def test_structured_copper_readback_preserves_full_precision_net_and_via(self):
        tracks = {"result": {"content": [{"text": json.dumps({"tracks": [
            {"uuid": "11111111-1111-1111-1111-111111111111",
             "start": {"x_mm": 1.234567, "y_mm": 3.456789}, "end": {"x_mm": 2.345678, "y_mm": 4.5},
             "layer": "F.Cu", "width_mm": 0.2, "net": "POWER 12V"}
        ]})}]}}
        vias = {"result": {"content": [{"text": json.dumps({"vias": [
            {"uuid": "22222222-2222-2222-2222-222222222222", "position": {"x_mm": 2.5, "y_mm": 3.5},
             "net": "GND", "layers": ["F.Cu", "B.Cu"], "diameter_mm": 0.6, "drill_mm": 0.3}
        ]})}]}}
        parsed_track = parse_live_tracks(tracks)[0]
        self.assertEqual(parsed_track["net"], "POWER 12V")
        self.assertAlmostEqual(parsed_track["start"]["x_mm"], 1.234567)
        parsed_via = parse_live_vias(vias)[0]
        self.assertEqual(parsed_via["drill_mm"], 0.3)

    def test_text_track_parser_drops_display_id_from_net_name(self):
        response = {"result": {"content": [{"text":
            "1. (30.00, 30.00) -> (70.00, 30.00) mm layer=BL_F_Cu "
            "width=0.250 mm net=POWER 12V id=9b94c8a0..."}]}}
        self.assertEqual(parse_live_tracks(response)[0]["net"], "POWER 12V")
    def test_symbol_and_pin_parsers_preserve_named_usb_shield_pin(self):
        symbols = parse_schematic_symbols(response(
            "Symbols (1 total):\n- J1 USB Connector:USB_C_Receptacle_USB2.0_16P @ (10.00, 20.00) rot=0 unit=1"
        ))
        self.assertEqual(symbols[0].library, "Connector")
        pins = parse_pin_positions(response("Connector:USB_C_Receptacle_USB2.0_16P @ (10, 20):\n"
                                            "- Pin SH: (2.5, 3.5) mm"))
        self.assertEqual(pins["SH"], (2.5, 3.5))

    def test_named_no_connect_uses_exact_pin_and_reports_erc_delta(self):
        calls = []
        erc_reports = [
            {"findings": [{"id": "shield-not-connected"}, {"id": "other"}]},
            {"findings": [{"id": "other"}]},
        ]

        def call(name, arguments):
            calls.append((name, arguments))
            if name == "sch_get_symbols":
                return response("Symbols (1 total):\n- J1 USB Connector:USB_C_Receptacle_USB2.0_16P @ (10.00, 20.00) rot=0 unit=1")
            if name == "sch_get_pin_positions":
                return response("Connector:USB_C_Receptacle_USB2.0_16P @ (10, 20):\n"
                                "- Pin SH: (12.5, 23.5) mm")
            if name == "sch_add_no_connect":
                return response("No-connect added")
            if name == "run_erc":
                return response(json.dumps(erc_reports.pop(0)))
            raise AssertionError(name)

        result = McpLiveAdapter(call).add_no_connect_by_pin("J1", "SH")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["resolved_pin"]["canonical_pin"], "SH")
        self.assertFalse(result["saved"])
        self.assertTrue(result["dirty"])
        add_call = next(item for item in calls if item[0] == "sch_add_no_connect")
        self.assertEqual(add_call[1], {"x_mm": 12.5, "y_mm": 23.5, "snap_to_grid": False})
        self.assertEqual(result["erc"]["removed_finding_ids"], ["shield-not-connected"])

    def test_named_no_connect_rejects_stale_revision_before_write(self):
        calls = []

        def call(name, arguments):
            calls.append(name)
            raise AssertionError("stale check must reject before any MCP call")

        adapter = McpLiveAdapter(call, revision=lambda: "new")
        result = adapter.add_no_connect_by_pin("J1", "SH", expected_revision="old")
        self.assertEqual(result["status"], "failure")
        self.assertFalse(calls)

    def test_domain_refusal_is_not_reported_as_transport_success(self):
        def call(name, arguments):
            return response("Refusing file-based PCB sync while a board is open in KiCad.")

        with self.assertRaisesRegex(Exception, "refused"):
            McpLiveAdapter(call).checked_mutation("pcb_sync_from_schematic")

    def test_live_drc_preview_is_selective_and_execution_fails_closed(self):
        def call(name, arguments):
            if name == "run_drc":
                return response(json.dumps({"metadata": {"violations": [
                    {"uuid": "v1", "type": "clearance", "items": []},
                    {"uuid": "v2", "type": "unconnected_items", "items": []},
                ]}}))
            raise AssertionError(name)

        adapter = McpLiveAdapter(call)
        preview = adapter.preview_drc_exclusions(DrcExclusionFilter(types=frozenset({"clearance"})))
        self.assertEqual(preview["excluded_uuids"], ["v1"])
        result = adapter.execute_drc_exclusions(preview)
        self.assertEqual(result["status"], "failure")
        self.assertFalse(result["verified_effects"]["mutated"])

    def test_ratsnest_consumes_kicad10_fallback(self):
        def call(name, arguments):
            if name == "pcb_get_ratsnest":
                return response("Live ratsnest extraction is not exposed by KiCad 10.x IPC.")
            if name == "get_unconnected_nets":
                return response("Unconnected nets (1 total):\n- [error] Missing connection")
            if name == "run_drc":
                report = {"evidence": [{"violations": {
                    "unconnected_items": [{"type": "unconnected_items", "items": [
                        {"uuid": "pad-a", "pos": {"x": 1, "y": 2}},
                        {"uuid": "pad-b", "pos": {"x": 3, "y": 4}},
                    ]}], "violations": []
                }}]}
                return response(json.dumps(report))
            raise AssertionError(name)

        result = McpLiveAdapter(call).ratsnest()
        self.assertEqual(result["source"], "get_unconnected_nets+drc")
        self.assertTrue(result["fallback"])
        self.assertTrue(result["available"])
        self.assertEqual(result["endpoints"][0]["items"][0]["uuid"], "pad-a")
        self.assertTrue(result["limitations"])

    def test_ratsnest_falls_back_when_native_tool_is_transport_unavailable(self):
        def call(name, arguments):
            if name == "pcb_get_ratsnest":
                return response("ratsnest tool unavailable", error=True)
            if name == "get_unconnected_nets":
                return response("Unconnected nets (0 total):")
            if name == "run_drc":
                return response(json.dumps({"evidence": [{"violations": {}}]}))
            raise AssertionError(name)

        result = McpLiveAdapter(call).ratsnest()
        self.assertTrue(result["fallback"])
        self.assertEqual(result["source"], "get_unconnected_nets+drc")
        self.assertFalse(result["available"])


if __name__ == "__main__":
    unittest.main()
