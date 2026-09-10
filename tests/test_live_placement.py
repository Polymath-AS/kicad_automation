import copy
import unittest

from scripts.kicad_live_placement import parse_live_footprints
from scripts.kicad_promotion import PlacementPromotion


class LivePlacementTests(unittest.TestCase):
    def test_parse_footprint_listing(self):
        response = {"result": {"structuredContent": {"result":
            "Footprints (2 total):\n"
            "- J1 (J1) @ (30.00, 30.00) mm layer=BL_F_Cu id=681681d4...\n"
            "- J2 (J2) @ (70.00, 30.00) mm layer=BL_F_Cu id=b38844ce..."}}}
        items = parse_live_footprints(response)
        self.assertEqual([item["reference"] for item in items], ["J1", "J2"])
        self.assertEqual(items[0]["position"], {"x_mm": 30.0, "y_mm": 30.0})

    def test_parse_preserves_rotation_and_rejects_truncated_native_uuid(self):
        response = {"result": {"structuredContent": {"result":
            "Footprints (1 total):\n"
            "- J1 (J1) @ (30.00, 30.00) mm layer=F.Cu rot=90 id=681681d4..."}}}
        items = parse_live_footprints(response)
        self.assertEqual(items[0]["rotation"], 90.0)
        self.assertNotIn("uuid", items[0])
        self.assertEqual(items[0]["uuid_display"], "681681d4...")

    def test_live_style_placement_rollback_after_save(self):
        board = {"footprints": [
            {"reference": "J1", "position": {"x_mm": 30.0, "y_mm": 30.0}},
            {"reference": "J2", "position": {"x_mm": 70.0, "y_mm": 30.0}},
        ]}
        saved = copy.deepcopy(board)
        fail_after_save = True

        def read():
            return copy.deepcopy(board)

        def apply(delta):
            for change in delta["changed_footprints"]:
                item = next(fp for fp in board["footprints"] if fp["reference"] == change["reference"])
                item["position"] = change["position"]
            return {"moved_footprints": len(delta["changed_footprints"])}

        def restore(snapshot):
            board.clear()
            board.update(copy.deepcopy(snapshot))

        def save():
            nonlocal saved
            saved = copy.deepcopy(board)
            return True

        def reopen():
            board.clear()
            board.update(copy.deepcopy(saved))

        def validate():
            nonlocal fail_after_save
            if fail_after_save:
                fail_after_save = False
                return False
            return True

        candidate = copy.deepcopy(board)
        candidate["footprints"][0]["position"] = {"x_mm": 35.0, "y_mm": 30.0}
        result = PlacementPromotion(
            read_board=read, snapshot=read, apply_delta=apply, restore=restore,
            save=save, reopen=reopen, validate=validate,
        ).promote(candidate)
        self.assertEqual(result["status"], "failure")
        self.assertTrue(result["verified_effects"]["rollback_verified"])
        self.assertEqual(board, {
            "footprints": [
                {"reference": "J1", "position": {"x_mm": 30.0, "y_mm": 30.0}},
                {"reference": "J2", "position": {"x_mm": 70.0, "y_mm": 30.0}},
            ]
        })
        # The source document is restored even though the postcondition failed
        # after the first save; callers can now retry from the original state.
        self.assertEqual(saved, board)


if __name__ == "__main__":
    unittest.main()
