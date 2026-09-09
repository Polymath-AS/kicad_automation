import copy
import unittest

from scripts.kicad_contracts import (
    DrcExclusionFilter,
    DocumentState,
    RevisionConflict,
    RevisionStore,
    annotate_tools,
    decorate_inspection,
    precise_schematic_schema,
    preserve_footprint_ids,
    select_drc_violations,
    transactional_delete,
    validate_hole_constraints,
)
from scripts.kicad_placement import PlacementRequest, apply_placement
from scripts.kicad_schematic import NoConnectRequest, add_no_connect, build_circuit, no_connect_pin_input
from scripts.kicad_topology import RouteRequest, TransactionalRouter
from scripts.pad_to_pad_regression import resolve_pad, route_arguments


class DesignContractTests(unittest.TestCase):
    def test_stable_catalog_keeps_unavailable_tools_discoverable(self):
        catalog = annotate_tools([{"name": "pcb_save", "inputSchema": {}}], live_ipc=False)
        save = next(item for item in catalog if item["name"] == "pcb_save")
        self.assertEqual(save["availability"], "unavailable")
        self.assertEqual(save["backend"], "live_ipc")
        self.assertEqual(decorate_inspection("pad", [{"reference": "J1", "number": "1"}])[0]["uuid"],
                         decorate_inspection("pad", [{"reference": "J1", "number": "1"}])[0]["uuid"])

    def test_revision_store_rejects_stale_before_callback(self):
        store = RevisionStore({"value": 1})
        called = []
        result = store.transact("edit", lambda value: called.append(value), expected_revision=3)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(called, [])
        with self.assertRaises(RevisionConflict):
            store.check_revision(3)

    def test_revision_store_rolls_back_postcondition_failure(self):
        store = RevisionStore({"value": 1})
        result = store.transact("edit", lambda value: value.update(value=2), verify=lambda *_: False)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(store.document, {"value": 1})
        self.assertEqual(store.state.document_revision, 0)

    def test_topology_dry_run_and_atomic_impossible_route(self):
        board = {"bounds": {"left": 0, "bottom": 0, "right": 20, "top": 20},
                 "footprints": [], "keepouts": [{"bounds": {"left": 0, "bottom": 0, "right": 20, "top": 20}, "uuid": "wall"}]}
        original = copy.deepcopy(board)
        state = {"tracks": []}
        router = TransactionalRouter(snapshot=lambda: copy.deepcopy(state), apply=lambda plan: state["tracks"].extend(plan.segments),
                                     restore=lambda old: state.update(old), validate=lambda: True)
        failed = router.route(RouteRequest((1, 1), (19, 19), "N"), board)
        self.assertEqual(failed["status"], "failure")
        self.assertTrue(failed["blockers"])
        self.assertEqual(board, original)
        preview_board = {"bounds": {"left": 0, "bottom": 0, "right": 20, "top": 20}, "footprints": []}
        preview = router.route(RouteRequest((1, 1), (19, 19), "N", dry_run=True), preview_board)
        self.assertEqual(preview["status"], "success")
        self.assertTrue(preview["verified_effects"]["dry_run"])
        self.assertEqual(state["tracks"], [])
        multilayer = router.route(RouteRequest((1, 1), (19, 19), "N", layers=("F.Cu", "B.Cu"),
                                                allow_vias=True), preview_board)
        self.assertEqual(multilayer["status"], "success")
        self.assertTrue(multilayer["verified_effects"]["plan"]["vias"])

    def test_constrained_placement_success_and_unsatisfiable_failure(self):
        board = {"bounds": {"left": 0, "bottom": 0, "right": 20, "top": 20},
                 "footprints": [
                     {"reference": "J1", "position": {"x_mm": 3, "y_mm": 10}, "size": {"width": 2, "height": 2}},
                     {"reference": "U1", "position": {"x_mm": 10, "y_mm": 10}, "size": {"width": 4, "height": 4}},
                 ]}
        result = apply_placement(board, [PlacementRequest("J1", (2, 10), connector_edge="left")])
        self.assertEqual(result["status"], "success")
        self.assertEqual(board["footprints"][0]["position"]["x_mm"], 2)
        before = copy.deepcopy(board)
        bad = apply_placement(board, [PlacementRequest("J1", (100, 100), search_radius=0)])
        self.assertEqual(bad["status"], "failure")
        self.assertEqual(board, before)
        keepout_board = {"bounds": {"left": 0, "bottom": 0, "right": 20, "top": 20},
                         "antenna_keepouts": [{"left": 0, "bottom": 0, "right": 8, "top": 8}],
                         "footprints": [{"reference": "U2", "position": {"x_mm": 10, "y_mm": 10},
                                         "size": {"width": 2, "height": 2}}]}
        blocked = apply_placement(keepout_board, [PlacementRequest("U2", (4, 4), search_radius=0)])
        self.assertEqual(blocked["status"], "failure")

    def test_pin_no_connect_uses_named_shield_and_save_state(self):
        symbols = [{"reference": "J1", "pins": [{"number": "S1", "name": "SH", "position": {"x_mm": 12, "y_mm": 3}}]}]
        request = NoConnectRequest.from_mapping({"reference": "J1", "pin": "S1"})
        self.assertEqual(no_connect_pin_input(request, symbols)["canonical_pin"], "SH")
        result = add_no_connect(request, symbols, lambda payload: {"verified": payload}, save=lambda: True)
        self.assertEqual(result["status"], "success")
        self.assertFalse(result["dirty"])
        self.assertTrue(result["saved"])
        self.assertEqual(NoConnectRequest.from_mapping({"x_mm": 1200, "y_mm": 2}).x_mm, 1200)
        self.assertAlmostEqual(NoConnectRequest.from_mapping({"x_mm": 1200, "y_mm": 2, "unit": "nm"}).x_mm, 0.0012)

    def test_no_connect_save_failure_rolls_back_when_adapter_supplies_checkpoint(self):
        design = {"no_connects": []}
        result = add_no_connect(
            NoConnectRequest.from_mapping({"x_mm": 1, "y_mm": 2}), [],
            lambda payload: design["no_connects"].append(payload), save=lambda: False,
            snapshot=lambda: copy.deepcopy(design), restore=lambda old: design.update(old),
        )
        self.assertEqual(result["status"], "failure")
        self.assertEqual(design["no_connects"], [])

    def test_builder_validates_nested_request_before_mutating(self):
        calls = []
        invalid = {"symbols": [{"lib_id": "Connector_Generic:Conn_01x01", "reference": "J1"}]}
        result = build_circuit(invalid, lambda request: calls.append(request))
        self.assertEqual(result["status"], "failure")
        self.assertEqual(calls, [])
        self.assertIn("library", precise_schematic_schema()["properties"]["symbols"]["items"]["properties"])

    def test_selective_drc_exclusion_requires_filters_and_preview(self):
        findings = [{"uuid": "u1", "type": "clearance", "rule": "clearance"},
                    {"uuid": "u2", "type": "unconnected_items"}]
        preview = select_drc_violations(findings, DrcExclusionFilter(uuids=frozenset({"u1"})))
        self.assertEqual(preview["count"], 1)
        with self.assertRaises(ValueError):
            select_drc_violations(findings, DrcExclusionFilter())

    def test_hole_constraints_distinguish_board_rule_from_library_exception(self):
        result = validate_hole_constraints([
            {"reference": "J1", "pads": [{"number": "1", "type": "through_hole", "drill": 0.1}]},
            {"reference": "U1", "pads": [{"number": "1", "type": "npth", "drill": 0.1, "library_internal": True}]},
        ], min_through_hole=0.2, min_npth=0.2)
        self.assertEqual(result["status"], "violations")
        self.assertEqual(result["violations"][0]["classification"], "board_rule_violation")
        self.assertEqual(result["library_exceptions"][0]["classification"], "footprint_internal_library_exception")

    def test_qualified_footprint_id_parity_is_reported(self):
        result = preserve_footprint_ids(
            [{"reference": "J1", "footprint_id": "Connector:Header_1x01"}],
            [{"reference": "J1", "footprint": "Header_1x01"}],
        )
        self.assertFalse(result["parity"])
        self.assertEqual(result["mismatches"][0]["expected"], "Connector:Header_1x01")

    def test_delete_failure_is_domain_failure_and_rolls_back(self):
        board = {"items": ["a"]}
        result = transactional_delete("pcb_delete_items", ["a"], snapshot=lambda: copy.deepcopy(board),
                                      delete=lambda ids: board["items"].clear(), verify=lambda ids: False,
                                      restore=lambda old: board.update(old), state=DocumentState())
        self.assertEqual(result["status"], "failure")
        self.assertTrue(result["isError"])
        self.assertEqual(board["items"], ["a"])

    def test_pad_regression_resolves_named_pads_and_schema_variants(self):
        pads = {"pads": [{"reference": "J1", "number": "1", "net": "SIGNAL"},
                          {"reference": "J2", "number": "1", "net": "SIGNAL"}]}
        self.assertEqual(resolve_pad(pads, "J1", "1")["net"], "SIGNAL")
        schema = {"inputSchema": {"required": ["from_pad", "to_pad"],
                                   "properties": {"from_pad": {}, "to_pad": {}}}}
        args = route_arguments(schema, ("J1", "1"), ("J2", "1"))
        self.assertEqual(args["from_pad"]["reference"], "J1")
        self.assertEqual(args["to_pad"]["pad"], "1")


if __name__ == "__main__":
    unittest.main()
