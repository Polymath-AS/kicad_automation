import copy
import json
import unittest
from pathlib import Path

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
    execute_drc_exclusions,
    resolve_project_paths,
    transactional_delete,
    validate_hole_constraints,
)
from scripts.kicad_placement import PlacementRequest, apply_placement
from scripts.kicad_placement import promote_placement_candidate
from scripts.kicad_promotion import LivePromotion, TransactionalPromotion, board_digest, geometry_delta, placement_delta
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
        self.assertEqual(decorate_inspection("track", [{"uuid": "native-1"}])[0]["uuid_source"], "native")
        self.assertEqual(decorate_inspection("track", [{"id": "native-2"}])[0]["uuid"], "native-2")
        self.assertEqual(decorate_inspection("track", [{"start": {"x": 1}}])[0]["uuid_source"], "derived")

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

    def test_board_digest_is_collection_order_insensitive(self):
        first = {"tracks": [{"uuid": "a", "start": {"x": 1}}, {"uuid": "b", "start": {"x": 2}}]}
        second = {"tracks": list(reversed(first["tracks"]))}
        self.assertEqual(board_digest(first), board_digest(second))

    def test_same_uuid_copper_edit_is_detected_before_promotion(self):
        source = {"tracks": [{"uuid": "t1", "start": {"x_mm": 1, "y_mm": 1},
                              "end": {"x_mm": 2, "y_mm": 1}, "layer": "F.Cu",
                              "net": "N", "width_mm": 0.2}]}
        candidate = copy.deepcopy(source)
        candidate["tracks"][0]["width_mm"] = 0.3
        delta = geometry_delta(source, candidate)
        self.assertEqual([item["uuid"] for item in delta.changed_segments], ["t1"])

    def test_apply_exception_after_first_write_attempts_rollback(self):
        board = {"tracks": []}
        saved = copy.deepcopy(board)
        def read(): return board
        def snapshot(): return copy.deepcopy(board)
        def apply(_delta):
            board["tracks"].append({"uuid": "t1"})
            raise RuntimeError("second object failed")
        def restore(old): board.clear(); board.update(copy.deepcopy(old))
        def save(): saved.clear(); saved.update(copy.deepcopy(board)); return True
        def reopen(): board.clear(); board.update(copy.deepcopy(saved))
        result = TransactionalPromotion(
            read_document=read, snapshot=snapshot, apply=apply, restore=restore,
            save=save, reopen=reopen, validate=lambda: True,
            verify_readback=lambda *_: (True, None), operation="routing_promote",
        ).promote({}, object())
        self.assertEqual(result["status"], "failure")
        self.assertTrue(result["verified_effects"]["rollback_attempted"])
        self.assertTrue(result["verified_effects"]["rollback_verified"])
        self.assertEqual(board, {"tracks": []})

    def test_placement_delta_preserves_rotation_and_layer(self):
        source = {"footprints": [{"uuid": "f1", "reference": "J1",
                                   "position": {"x_mm": 1, "y_mm": 1},
                                   "rotation": 90, "layer": "F.Cu"}]}
        candidate = copy.deepcopy(source)
        candidate["footprints"][0]["position"] = {"x_mm": 2, "y_mm": 1}
        candidate["footprints"][0]["rotation"] = 180
        delta = placement_delta(source, candidate)
        self.assertEqual(delta["changed_footprints"][0]["rotation"], 180)

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

    def test_connector_rf_intent_fixture_covers_edge_antenna_and_locked_parts(self):
        fixture = json.loads(Path("tests/fixtures/placement-intent/placement_intent.json").read_text())
        valid = copy.deepcopy(fixture)
        result = apply_placement(valid, [
            PlacementRequest.from_mapping({"reference": "J1", "position": {"x_mm": 2, "y_mm": 15}}),
            PlacementRequest.from_mapping({"reference": "U1", "position": {"x_mm": 20, "y_mm": 15}}),
        ])
        self.assertEqual(result["status"], "success")
        self.assertEqual(valid["footprints"][0]["position"]["x_mm"], 2)

        before = copy.deepcopy(fixture)
        blocked_antenna = apply_placement(
            fixture, [PlacementRequest.from_mapping({
                "reference": "U1", "position": {"x_mm": 36, "y_mm": 15}, "search_radius": 0,
            })],
        )
        self.assertEqual(blocked_antenna["status"], "failure")
        self.assertEqual(fixture, before)

        locked = apply_placement(
            fixture, [PlacementRequest.from_mapping({
                "reference": "J2", "position": {"x_mm": 20, "y_mm": 26}, "search_radius": 0,
            })],
        )
        self.assertEqual(locked["status"], "failure")
        self.assertEqual(fixture, before)

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
        applied = execute_drc_exclusions(
            findings, DrcExclusionFilter(uuids=frozenset({"u1"})), preview=preview,
            add_exclusions=lambda ids: {"stored": ids},
        )
        self.assertEqual(applied["status"], "success")
        self.assertEqual(applied["verified_effects"]["selected_uuids"], ["u1"])
        zero_preview = select_drc_violations(findings, DrcExclusionFilter(types=frozenset({"missing"})))
        self.assertEqual(zero_preview["count"], 0)
        with self.assertRaises(ValueError):
            execute_drc_exclusions(findings, DrcExclusionFilter(types=frozenset({"missing"})),
                                    preview=zero_preview, add_exclusions=lambda ids: {"stored": ids})
        with self.assertRaises(ValueError):
            select_drc_violations(findings, DrcExclusionFilter(types=frozenset({"clearance", "unconnected_items"})), dry_run=False)
        with self.assertRaises(ValueError):
            execute_drc_exclusions(
                findings, DrcExclusionFilter(uuids=frozenset({"u2"})), preview=preview,
                add_exclusions=lambda ids: {"stored": ids},
            )

    def test_drc_selector_categories_narrow_with_and_semantics(self):
        findings = [
            {"uuid": "u1", "type": "clearance", "rule": "r1", "references": ["J1"]},
            {"uuid": "u2", "type": "clearance", "rule": "r2", "references": ["J2"]},
        ]
        preview = select_drc_violations(
            findings, DrcExclusionFilter(rules=frozenset({"r1"}), types=frozenset({"clearance"}),
                                          references=frozenset({"J1"})),
        )
        self.assertEqual(preview["excluded_uuids"], ["u1"])

    def test_drc_exclusion_save_failure_restores_snapshot(self):
        findings = [{"uuid": "u1", "type": "clearance"}]
        selector = DrcExclusionFilter(uuids=frozenset({"u1"}))
        preview = select_drc_violations(findings, selector)
        design = {"exclusions": []}
        result = execute_drc_exclusions(
            findings, selector, preview=preview,
            add_exclusions=lambda ids: design["exclusions"].extend(ids),
            save=lambda: False,
            snapshot=lambda: copy.deepcopy(design),
            restore=lambda old: design.update(old),
        )
        self.assertEqual(result["status"], "failure")
        self.assertTrue(result["verified_effects"]["rolled_back"])
        self.assertEqual(design, {"exclusions": []})

    def test_project_destination_semantics_include_windows_paths(self):
        parent = resolve_project_paths(Path("C:/workspace"), "build/board")
        self.assertTrue(parent["project"].endswith("build\\board\\board.kicad_pro") or parent["project"].endswith("build/board/board.kicad_pro"))
        named = resolve_project_paths(Path("C:/workspace"), "C:\\CAD\\board")
        self.assertTrue(named["project"].endswith("CAD\\board\\board.kicad_pro"))
        file_path = resolve_project_paths(Path("C:/workspace"), "C:\\CAD\\board\\board.kicad_pcb")
        self.assertTrue(file_path["board"].endswith("CAD\\board\\board.kicad_pcb"))

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

    def _live_board(self):
        board = {"tracks": [], "vias": [], "footprints": [{
            "uuid": "fp-1", "reference": "J1", "position": {"x_mm": 2, "y_mm": 2},
        }]}
        saved = copy.deepcopy(board)
        calls = {"save": 0, "reopen": 0}

        def read():
            return board

        def snapshot():
            return copy.deepcopy(board)

        def apply(delta):
            board["tracks"].extend(copy.deepcopy(delta.add_segments))
            board["vias"].extend(copy.deepcopy(delta.add_vias))
            return {"applied_tracks": len(delta.add_segments)}

        def restore(old):
            board.clear()
            board.update(copy.deepcopy(old))

        def save():
            calls["save"] += 1
            saved.clear()
            saved.update(copy.deepcopy(board))
            return True

        def reopen():
            calls["reopen"] += 1
            board.clear()
            board.update(copy.deepcopy(saved))

        return board, saved, calls, read, snapshot, apply, restore, save, reopen

    def test_routing_promotion_saves_reopens_and_preserves_net(self):
        board, _saved, calls, read, snapshot, apply, restore, save, reopen = self._live_board()
        candidate = copy.deepcopy(board)
        candidate["tracks"].append({"uuid": "t1", "start": {"x_mm": 2, "y_mm": 2},
                                     "end": {"x_mm": 10, "y_mm": 2}, "layer": "F.Cu",
                                     "net": "SIGNAL", "width_mm": 0.25})
        promotion = LivePromotion(read_board=read, snapshot=snapshot, apply_delta=apply,
                                  restore=restore, save=save, reopen=reopen, validate=lambda: True)
        result = promotion.promote(candidate, expected_revision=0,
                                   expected_source_hash=board_digest(board))
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["verified_effects"]["readback_verified"])
        self.assertTrue(result["verified_effects"]["post_validation"])
        self.assertEqual(calls["reopen"], 1)
        self.assertEqual(board["tracks"][0]["net"], "SIGNAL")
        self.assertFalse(result["dirty"])
        self.assertTrue(result["saved"])

    def test_routing_promotion_postcondition_failure_rolls_back_and_reopens(self):
        board, saved, calls, read, snapshot, apply, restore, save, reopen = self._live_board()
        original = copy.deepcopy(board)
        candidate = copy.deepcopy(board)
        candidate["tracks"].append({"uuid": "t1", "start": {"x_mm": 2, "y_mm": 2},
                                     "end": {"x_mm": 10, "y_mm": 2}, "layer": "F.Cu",
                                     "net": "SIGNAL"})
        validations = iter((False, True))
        promotion = LivePromotion(read_board=read, snapshot=snapshot, apply_delta=apply,
                                  restore=restore, save=save, reopen=reopen,
                                  validate=lambda: next(validations))
        result = promotion.promote(candidate)
        self.assertEqual(result["status"], "failure")
        self.assertTrue(result["verified_effects"]["rolled_back"])
        self.assertTrue(result["verified_effects"]["rollback_verified"])
        self.assertEqual(board, original)
        self.assertEqual(saved, original)
        self.assertEqual(calls["reopen"], 2)

    def test_routing_promotion_rejects_stale_before_apply(self):
        board, _saved, _calls, read, snapshot, apply, restore, save, reopen = self._live_board()
        called = []
        promotion = LivePromotion(read_board=read, snapshot=snapshot,
                                  apply_delta=lambda delta: called.append(delta), restore=restore,
                                  save=save, reopen=reopen, validate=lambda: True)
        result = promotion.promote({**board, "tracks": [{"uuid": "t1", "net": "N"}]},
                                   expected_revision=2)
        self.assertEqual(result["status"], "failure")
        self.assertEqual(called, [])
        self.assertEqual(board["tracks"], [])

    def test_placement_promotion_uses_same_rollback_contract(self):
        board = {"bounds": {"left": 0, "bottom": 0, "right": 20, "top": 20},
                 "footprints": [{"uuid": "fp-1", "reference": "J1",
                                 "position": {"x_mm": 4, "y_mm": 10},
                                 "size": {"width": 2, "height": 2}, "intent": {"edge": "left"}}]}
        saved = copy.deepcopy(board)
        def read(): return board
        def snapshot(): return copy.deepcopy(board)
        def apply(delta):
            for change in delta["changed_footprints"]:
                next(item for item in board["footprints"] if item["uuid"] == change["uuid"])["position"] = change["position"]
        def restore(old): board.clear(); board.update(copy.deepcopy(old))
        def save(): saved.clear(); saved.update(copy.deepcopy(board)); return True
        def reopen(): board.clear(); board.update(copy.deepcopy(saved))
        candidate = copy.deepcopy(board)
        candidate["footprints"][0]["position"] = {"x_mm": 2, "y_mm": 10}
        result = promote_placement_candidate(board, candidate, read_board=read, snapshot=snapshot,
                                             apply_delta=apply, restore=restore, save=save,
                                             reopen=reopen, validate=lambda: True)
        self.assertEqual(result["status"], "success")
        self.assertEqual(board["footprints"][0]["position"]["x_mm"], 2)


if __name__ == "__main__":
    unittest.main()
