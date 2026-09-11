"""Core regression tests: host unittest and installed-module Docker build gate."""

import hashlib
import json
import math
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from PIL import Image

try:
    from kicad_mcp.tools import pcb_visual_review as review
except ImportError:
    from scripts import pcb_visual_review as review


SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="80mm" height="40mm" '
       'viewBox="0 0 80 40"><path fill="#C83434" d="M 1,1 L 40,20 L 3,30 Z"/></svg>')


class VisualReviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)
        self.project = self.workspace / "project"
        self.project.mkdir()
        self.board = self.project / "project.kicad_pcb"
        self.board.write_bytes(b"frozen-board-unit-test")
        self.pro = self.board.with_suffix(".kicad_pro")
        self.pro.write_text('{"text_variables":{"revision":"A"}}', encoding="utf-8")
        self.store = review.ReviewStore(self.workspace, self.project, self.project / "output", self.board)
        self.exported_sources = []
        self.after_export = None
        self.fail_view = None
        self.fail_version = False
        self.commands = []
        self.run = mock.patch.object(review, "_run", side_effect=self.fake_run).start()
        self.raster = mock.patch.object(review, "_raster", side_effect=self.fake_raster).start()
        self.addCleanup(mock.patch.stopall)

    def fake_run(self, args, timeout, env=None):
        self.commands.append(args)
        if args[-1] == "version":
            if self.fail_version:
                raise subprocess.TimeoutExpired(args, timeout)
            return "10.0.4"
        if args[-1] == "--version":
            return "rsvg-convert version 2.60.0"
        destination = Path(args[args.index("--output") + 1])
        frozen = Path(args[-1])
        self.exported_sources.append(frozen.read_bytes())
        self.assertNotEqual(frozen, self.board)
        self.assertTrue(frozen.is_relative_to(self.store.root))
        self.assertTrue(Path(env["XDG_CONFIG_HOME"]).is_relative_to(self.store.root))
        destination.write_text(SVG, encoding="utf-8")
        if self.after_export:
            self.after_export()
        if self.fail_view and destination.name.startswith(self.fail_view):
            raise RuntimeError("Deliberate export failure")
        return ""

    def fake_raster(self, svg, png, width, timeout):
        _, box = review._svg(svg)
        width, height = review._dimensions(box, width)
        Image.new("RGB", (width, height), "navy").save(png)
        return {"width_px": width, "height_px": height, "viewbox": box}

    def capture(self, **args):
        return self.store.capture(width=400, **args)

    def test_identical_captures_are_unique_and_preserve_every_artifact(self):
        first = self.capture(label="before")
        folder = self.workspace / first["artifact_dir"]
        original = {p.relative_to(folder): p.read_bytes() for p in folder.rglob("*") if p.is_file()}
        second = self.capture(label="after")
        self.assertNotEqual(first["review_id"], second["review_id"])
        self.assertEqual(first["source"]["sha256"], second["source"]["sha256"])
        self.assertEqual(first["status"], "ok")
        for name, content in original.items():
            self.assertEqual((folder / name).read_bytes(), content)
        self.assertEqual(self.board.read_bytes(), b"frozen-board-unit-test")
        self.assertEqual(len(first["views"]), 2)
        self.assertEqual(len(first["artifacts"]), 8)  # board, project, two raw/SVG/PNG triples
        self.assertNotIn("F.Mask", first["views"][0]["layers"])
        self.assertTrue(first["views"][1]["mirrored"])
        self.assertIn("--mirror", self.commands[-1])

    def test_all_views_render_same_frozen_bytes_when_source_changes(self):
        self.after_export = lambda: self.board.write_bytes(b"new-live-saved-state")
        record = self.capture()
        self.assertEqual(self.exported_sources, [b"frozen-board-unit-test"] * 2)
        self.assertEqual(record["source"]["sha256"],
                         hashlib.sha256(b"frozen-board-unit-test").hexdigest())
        self.assertIn("project/project.kicad_pcb", record["source"]["changed_during_capture"])
        self.assertTrue(record["warnings"])
        self.assertEqual(record["source"]["live_unsaved_changes"], "not_inspected")

    def test_project_settings_are_preserved_and_changes_reported(self):
        old_pro = self.pro.read_bytes()
        self.after_export = lambda: self.pro.write_bytes(b"new-settings")
        record = self.capture()
        snapshot = self.workspace / record["artifact_dir"] / "source" / self.pro.name
        self.assertEqual(snapshot.read_bytes(), old_pro)
        self.assertIn("project/project.kicad_pro", record["source"]["changed_during_capture"])

    def test_expected_digest_refuses_stale_board_without_artifacts(self):
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.capture(expected_sha256="0" * 64)
        self.assertFalse(self.store.root.exists())
        self.run.assert_not_called()

    def test_candidate_is_workspace_relative_but_history_belongs_to_active_project(self):
        candidate = self.workspace / "candidate.kicad_pcb"
        candidate.write_bytes(b"candidate")
        record = self.capture(board_path="candidate.kicad_pcb", expected_sha256=review._sha(b"candidate"))
        self.assertTrue(record["artifact_dir"].startswith("project/output/image-review/"))
        self.assertEqual(record["source"]["board_path"], "candidate.kicad_pcb")
        self.assertEqual(self.board.read_bytes(), b"frozen-board-unit-test")

    def test_invalid_paths_ids_views_sizes_and_labels_fail_before_rendering(self):
        for path in ("../outside.kicad_pcb", r"C:\outside.kicad_pcb", "project/project.kicad_pro"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.capture(board_path=path)
        for names in ([], ["all", "invalid"], ["bad"], ["top;rm"]):
            with self.subTest(views=names), self.assertRaises(ValueError):
                self.capture(views=names)
        for width in (1, 6001, True):
            with self.assertRaises(ValueError):
                self.store.capture(width=width)
        with self.assertRaises(ValueError):
            self.capture(label="x" * 241)
        for identifier in ("../escape", "/root", ".", "..", r"a\b"):
            with self.assertRaises(ValueError):
                self.store.load(identifier)
        self.run.assert_not_called()

    def test_custom_inner_layer_and_mirror(self):
        record = self.capture(layers=["In1.Cu", "Edge.Cuts"], mirror=True)
        self.assertEqual(record["views"][0]["name"], "custom")
        self.assertEqual(record["views"][0]["layers"], ["In1.Cu", "Edge.Cuts"])
        self.assertTrue(record["views"][0]["mirrored"])
        with self.assertRaises(ValueError):
            self.capture(views=["top"], layers=["In1.Cu"])
        with self.assertRaises(ValueError):
            self.capture(mirror=True)

    def test_partial_and_failed_exports_leave_journal_and_raw_images(self):
        self.fail_view = "bottom"
        partial = self.capture()
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(len(partial["views"]), 1)
        self.assertIn("Deliberate", partial["errors"][0]["error"])
        self.assertIn("bottom.raw.svg", [a["file"] for a in partial["artifacts"]])
        self.fail_view = "top"
        failure = self.capture(views=["top"])
        self.assertEqual(failure["status"], "failure")
        self.assertTrue((self.workspace / failure["manifest"]).exists())
        self.assertTrue((self.workspace / failure["report"]).exists())

    def test_timeout_leaves_failure_journal_and_source_copy(self):
        self.fail_version = True
        record = self.capture()
        self.assertEqual(record["status"], "failure")
        self.assertTrue((self.workspace / record["artifact_dir"] / "source" / self.board.name).exists())
        self.assertIn("timed out", record["errors"][0]["error"])

    def test_history_pagination_filter_and_no_read_side_effects(self):
        self.assertEqual(self.store.history()["reviews"], [])
        self.assertFalse(self.store.root.exists())
        first = self.capture(label="placement <phase>")
        second = self.capture(label="routing")
        third = self.capture(label="placement final")
        page = self.store.history(limit=1)
        self.assertEqual(page["reviews"][0]["review_id"], third["review_id"])
        next_page = self.store.history(limit=1, before_id=page["next_before_id"])
        self.assertEqual(next_page["reviews"][0]["review_id"], second["review_id"])
        filtered = self.store.history(label="placement")["reviews"]
        self.assertEqual([m["review_id"] for m in filtered], [third["review_id"], first["review_id"]])

    def test_get_returns_saved_image_without_export_or_raster(self):
        record = self.capture()
        calls = self.run.call_count, self.raster.call_count
        retrieved = self.store.get("latest", "top")
        self.assertEqual(retrieved["review_id"], record["review_id"])
        self.assertEqual((self.run.call_count, self.raster.call_count), calls)
        self.assertEqual(retrieved["images"][0], record["views"][0]["png"])

    def test_history_is_compact_and_skips_malformed_json_records(self):
        original = self.capture()
        legacy = self.store.root / "bad-record"
        legacy.mkdir()
        (legacy / "manifest.json").write_text("[]", encoding="utf-8")
        history = self.store.history()
        self.assertIn("bad-record", history["skipped_legacy_or_invalid"])
        summary = history["reviews"][0]
        self.assertNotIn("artifacts", summary)
        self.assertEqual(summary["views"], ["top", "bottom"])
        self.assertEqual(summary["manifest"], original["manifest"])

    def test_new_project_file_during_capture_is_reported_as_stale_context(self):
        self.pro.unlink()
        self.after_export = lambda: self.pro.write_text("{}", encoding="utf-8")
        record = self.capture()
        self.assertIn("project/project.kicad_pro", record["source"]["changed_during_capture"])

    def test_crop_uses_retained_vectors_and_is_also_retained(self):
        original = self.capture()
        calls = self.run.call_count
        cropped = self.store.get(original["review_id"], "top", [0.25, 0.25, 0.5, 0.5], 800)
        self.assertEqual(self.run.call_count, calls)
        self.assertEqual(cropped["kind"], "crop")
        self.assertEqual(cropped["viewbox"], [19, 9, 42, 22])
        self.assertEqual(cropped["width_px"], 800)
        self.assertEqual(cropped["parent_review_id"], original["review_id"])
        self.assertTrue((self.workspace / cropped["images"][0]["path"]).exists())
        self.assertEqual(self.store.get()["review_id"], original["review_id"])

    def test_padding_preserves_raw_export_and_exposes_board_edge(self):
        record = self.capture(views=["top"])
        view = record["views"][0]
        self.assertEqual(view["viewbox"], [-2, -2, 84, 44])
        raw = self.workspace / view["raw_svg"]["path"]
        self.assertEqual(raw.read_text(encoding="utf-8"), SVG)
        self.assertEqual(record["render"]["padding_mm"], 2)

    def test_invalid_crops_cannot_escape_view_or_exhaust_memory(self):
        record = self.capture()
        for crop in ([0, 0, 0, 1], [0.5, 0, 1, 1], [-1, 0, 1, 1],
                     [0, math.nan, 1, 1], [0, 0, 0.001, 1], [0, 0, 1]):
            with self.subTest(crop=crop), self.assertRaises(ValueError):
                self.store.get(record["review_id"], "top", crop)
        self.assertEqual(self.store.history()["total"], 1)

    def test_corrupt_png_and_svg_are_not_silently_returned(self):
        record = self.capture()
        (self.workspace / record["views"][0]["png"]["path"]).write_bytes(b"tamper")
        with self.assertRaisesRegex(ValueError, "changed since capture"):
            self.store.get(record["review_id"])
        (self.workspace / record["views"][1]["svg"]["path"]).write_bytes(b"tamper")
        with self.assertRaisesRegex(ValueError, "changed since capture"):
            self.store.get(record["review_id"], "bottom", [0, 0, 0.5, 0.5])

    def test_compare_is_persistent_without_reexport_or_claiming_pixel_diff(self):
        before, after = self.capture(label="before"), self.capture(label="after")
        calls = self.run.call_count
        compared = self.store.compare(before["review_id"], after["review_id"], width=800)
        self.assertEqual(compared["status"], "ok")
        self.assertEqual(self.run.call_count, calls)
        self.assertTrue(compared["same_board_bytes"])
        self.assertIn("NOT a registered pixel diff", compared["comparison"])
        self.assertTrue((self.workspace / compared["images"][0]["path"]).exists())
        self.assertEqual(self.store.history(kind="comparison")["total"], 3)

    def test_compare_refuses_different_custom_layers_or_orientation(self):
        before = self.capture(layers=["F.Cu"])
        after = self.capture(layers=["B.Cu"])
        with self.assertRaisesRegex(ValueError, "layers"):
            self.store.compare(before["review_id"], after["review_id"], view="custom")
        mirror = self.capture(layers=["F.Cu"], mirror=True)
        with self.assertRaisesRegex(ValueError, "mirrored"):
            self.store.compare(before["review_id"], mirror["review_id"], view="custom")

    def test_derived_images_can_be_retrieved_by_history_id_without_rendering(self):
        original = self.capture()
        crop = self.store.get(original["review_id"], crop=[0, 0, 0.5, 0.5], width=400)
        compare = self.store.compare(original["review_id"], original["review_id"], width=800)
        calls = self.run.call_count, self.raster.call_count
        for record in (crop, compare):
            self.assertEqual(self.store.get(record["review_id"])["images"], record["images"])
        self.assertEqual((self.run.call_count, self.raster.call_count), calls)
        with self.assertRaisesRegex(ValueError, "original capture"):
            self.store.get(crop["review_id"], crop=[0, 0, 0.5, 0.5])

    def test_gallery_escapes_labels_and_retains_legacy_folders(self):
        legacy = self.store.root / "old-review"
        legacy.mkdir(parents=True)
        (legacy / "old.png").write_bytes(b"legacy-retained")
        record = self.capture(label='<script>alert("oops")</script>')
        page = (self.workspace / record["gallery"]).read_text(encoding="utf-8")
        self.assertNotIn('<script>', page)
        self.assertIn("&lt;script&gt;", page)
        self.assertEqual((legacy / "old.png").read_bytes(), b"legacy-retained")
        self.assertIn("old-review", self.store.history()["skipped_legacy_or_invalid"])

    def test_concurrent_captures_do_not_overwrite_or_lose_history(self):
        with ThreadPoolExecutor(max_workers=3) as pool:
            records = list(pool.map(lambda i: self.capture(label=f"parallel-{i}"), range(3)))
        self.assertEqual(len({m["review_id"] for m in records}), 3)
        self.assertEqual(self.store.history()["total"], 3)
        gallery = (self.store.root / "index.html").read_text(encoding="utf-8")
        for record in records:
            self.assertIn(record["review_id"], gallery)

    def test_symlinks_cannot_read_outside_workspace_or_history(self):
        with tempfile.TemporaryDirectory() as outside:
            external = Path(outside) / "external.kicad_pcb"
            external.write_bytes(b"external")
            link = self.workspace / "linked.kicad_pcb"
            try:
                link.symlink_to(external)
            except OSError:
                self.skipTest("Symlink creation not permitted on this host")
            with self.assertRaises(ValueError):
                self.capture(board_path="linked.kicad_pcb")
            record = self.capture()
            png = self.workspace / record["views"][0]["png"]["path"]
            png.unlink()
            png.symlink_to(external)
            with self.assertRaises(ValueError):
                self.store.get(record["review_id"])

    def test_svg_rejects_external_or_active_content(self):
        path = self.workspace / "bad.svg"
        for fragment in ('<script/>', '<image href="file:///etc/passwd"/>',
                         '<path style="fill:url(http://example.invalid/a)"/>'):
            path.write_text(SVG.replace("</svg>", fragment + "</svg>"), encoding="utf-8")
            with self.assertRaises(ValueError):
                review._svg(path)


if __name__ == "__main__":
    unittest.main()
