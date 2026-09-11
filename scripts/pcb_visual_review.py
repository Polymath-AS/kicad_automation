"""Append-only PCB review artifacts; installed into kicad_mcp.tools by Docker.

The storage/rendering core is independent of MCP and never edits a source design.
Only register() imports the pinned upstream server. No GUI screenshots or SWIG.
"""

import base64
import hashlib
import html
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any


SCHEMA = "pcb-visual-review.v2"
BACKGROUND = "#18202b"
PADDING_MM = 2.0
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_EDGE = 6000
MAX_PIXELS = 16_000_000
SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)
_INDEX_LOCK = threading.RLock()
VIEW_SPECS = {
    "top": {"layers": ["F.Cu", "F.SilkS", "Edge.Cuts"], "mirrored": False},
    "bottom": {"layers": ["B.Cu", "B.SilkS", "Edge.Cuts"], "mirrored": True},
    "assembly_top": {
        "layers": ["F.Fab", "F.CrtYd", "F.SilkS", "Edge.Cuts"], "mirrored": False,
    },
    "assembly_bottom": {
        "layers": ["B.Fab", "B.CrtYd", "B.SilkS", "Edge.Cuts"], "mirrored": True,
    },
    "copper_top": {"layers": ["F.Cu", "Edge.Cuts"], "mirrored": False},
    "copper_bottom": {"layers": ["B.Cu", "Edge.Cuts"], "mirrored": True},
}
DEFAULT_VIEWS = ("top", "bottom")
_LAYERS = {
    "F.Cu", "B.Cu", "F.SilkS", "B.SilkS", "F.Mask", "B.Mask",
    "F.Paste", "B.Paste", "F.Fab", "B.Fab", "F.CrtYd", "B.CrtYd",
    "Edge.Cuts", "Margin", "Dwgs.User", "Cmts.User",
    *(f"In{i}.Cu" for i in range(1, 31)),
    *(f"User.{i}" for i in range(1, 46)),
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read(path: Path) -> bytes:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError(f"Artifact exceeds the {MAX_FILE_BYTES} byte limit: {path.name}")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("File grew beyond the size limit during reading.")
    return data


def _within(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"Path must stay within {root}.")
    return resolved


def _segment(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", value):
        raise ValueError("Expected a review/artifact ID, not a path.")
    return value


def _label(value: str) -> str:
    if len(value) > 240:
        raise ValueError("label must be at most 240 characters.")
    return value


def _width(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 400 <= value <= MAX_EDGE:
        raise ValueError(f"width must be an integer between 400 and {MAX_EDGE}.")
    return value


def _dimensions(viewbox: list[float], width: int) -> tuple[int, int]:
    if len(viewbox) != 4 or not all(math.isfinite(v) for v in viewbox):
        raise ValueError("SVG has an invalid viewBox.")
    if viewbox[2] <= 0 or viewbox[3] <= 0:
        raise ValueError("SVG has an empty viewport.")
    height = max(1, math.ceil(width * viewbox[3] / viewbox[2]))
    if height > MAX_EDGE or width * height > MAX_PIXELS:
        raise ValueError("Image is too tall/large; request a smaller width or a wider crop.")
    return width, height


def _views(names: list[str] | None, layers: list[str] | None, mirror: bool) -> dict:
    if layers is not None:
        if names is not None:
            raise ValueError("Use views OR custom layers, not both.")
        if not 1 <= len(layers) <= 40 or any(layer not in _LAYERS for layer in layers):
            raise ValueError("layers must contain 1–40 canonical KiCad layer names.")
        return {"custom": {"layers": list(dict.fromkeys(layers)), "mirrored": mirror}}
    if mirror:
        raise ValueError("mirror is only for custom layers; named views define orientation.")
    requested = list(DEFAULT_VIEWS if names is None else names)
    if requested == ["all"]:
        requested = list(VIEW_SPECS)
    if not requested or any(name not in VIEW_SPECS for name in requested):
        raise ValueError(f"views must be drawn from {list(VIEW_SPECS)}, or exactly ['all'].")
    return {name: VIEW_SPECS[name] for name in dict.fromkeys(requested)}


def _run(args: list[str], timeout: float, env: dict | None = None) -> str:
    result = subprocess.run(
        args, capture_output=True, text=True, errors="replace",
        timeout=timeout, check=False, env=env,
    )
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed ({result.returncode}): "
                           f"{(result.stderr or result.stdout)[-4000:]}")
    return result.stdout.strip()


def _svg(path: Path) -> tuple[ET.Element, list[float]]:
    data = _read(path)
    # Only local KiCad exports are accepted. Never resolve external SVG resources.
    if b"<!ENTITY" in data.upper():
        raise ValueError("SVG entities are not supported.")
    root = ET.fromstring(data)
    if root.tag != f"{{{SVG_NS}}}svg":
        raise ValueError("Not an SVG document.")
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] in {"script", "image", "foreignObject", "use"}:
            raise ValueError("SVG contains unsupported active/external content.")
        if any(key.rsplit("}", 1)[-1] == "href" or key.lower().startswith("on")
               or "url(" in value.lower() for key, value in node.attrib.items()):
            raise ValueError("SVG contains an external reference.")
    box = [float(v) for v in root.attrib["viewBox"].replace(",", " ").split()]
    _dimensions(box, 400)
    return root, box


def _raster(svg: Path, png: Path, width: int, timeout: float) -> dict:
    from PIL import Image

    _, box = _svg(svg)
    _dimensions(box, width)
    converter = shutil.which("rsvg-convert")
    if converter is None:
        raise RuntimeError("rsvg-convert is missing from the KiCad image.")
    _run([converter, "--width", str(width), "--keep-aspect-ratio",
          "--background-color", BACKGROUND, "--output", str(png), str(svg)], timeout)
    with Image.open(png) as img:
        if img.format != "PNG" or img.width > MAX_EDGE or img.height > MAX_EDGE:
            raise ValueError("Renderer produced an invalid or oversized PNG.")
        if img.width * img.height > MAX_PIXELS:
            raise ValueError("Renderer exceeded the pixel limit.")
        size = {"width_px": img.width, "height_px": img.height}
        img.verify()
    return {**size, "viewbox": box}


class ReviewStore:
    def __init__(self, workspace: Path, project: Path, output: Path,
                 board: Path | None, cli: str = "kicad-cli", timeout: float = 120):
        self.workspace = workspace.resolve()
        self.project = _within(self.workspace, project)
        self.root = _within(self.workspace, output / "image-review")
        self.board = board
        self.cli = cli
        self.timeout = timeout

    def relative(self, path: Path) -> str:
        return _within(self.workspace, path).relative_to(self.workspace).as_posix()

    def board_path(self, raw: str | None) -> Path:
        if raw is None:
            if self.board is None:
                raise ValueError("No saved PCB is configured.")
            board = self.board
        else:
            if PureWindowsPath(raw).drive or "\\" in raw:
                raise ValueError("Use a /workspace path, not a Windows host path.")
            requested = Path(raw)
            # Relative paths are unambiguously workspace-relative, never guessed.
            board = requested if requested.is_absolute() else self.workspace / requested
        board = _within(self.workspace, board)
        if board.suffix != ".kicad_pcb" or not board.is_file():
            raise ValueError("board_path must name an existing .kicad_pcb in the workspace.")
        return board

    def _new(self, kind: str, label: str) -> tuple[Path, dict]:
        label = _label(label)
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:48] or kind
        now = datetime.now(timezone.utc)
        review_id = f"{now.strftime('%Y%m%dT%H%M%S%fZ')}-{slug}-{uuid.uuid4().hex[:12]}"
        self.root.mkdir(parents=True, exist_ok=True)
        directory = _within(self.root, self.root / review_id)
        directory.mkdir(exist_ok=False)
        manifest = {
            "schema_version": SCHEMA, "review_id": review_id, "kind": kind,
            "status": "running", "label": label, "created_utc": now.isoformat(),
            "artifact_dir": self.relative(directory),
            "manifest": self.relative(directory / "manifest.json"),
            "report": self.relative(directory / "review.html"),
            "gallery": self.relative(self.root / "index.html"),
            "artifacts": [], "warnings": [], "errors": [],
        }
        self._save(directory, manifest)
        return directory, manifest

    def _save(self, directory: Path, manifest: dict) -> None:
        # Only this new run's journal and the derived gallery may be updated.
        with _INDEX_LOCK:
            temporary = directory / "manifest.pending"
            temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            temporary.replace(directory / "manifest.json")

    def _artifact(self, directory: Path, path: Path, **extra: Any) -> dict:
        path = _within(directory, path)
        data = _read(path)
        return {"file": path.relative_to(directory).as_posix(),
                "path": self.relative(path), "sha256": _sha(data), "bytes": len(data), **extra}

    def _verified(self, directory: Path, artifact: dict) -> Path:
        path = _within(directory, directory / artifact["file"])
        if _sha(_read(path)) != artifact["sha256"]:
            raise ValueError(f"Artifact changed since capture: {artifact['file']}")
        return path

    def _finish(self, directory: Path, manifest: dict, start: float) -> dict:
        manifest["elapsed_seconds"] = round(time.monotonic() - start, 3)
        self._save(directory, manifest)
        try:
            (directory / "review.html").write_text(self._page([manifest], directory),
                                                  encoding="utf-8")
            with _INDEX_LOCK:
                records, _ = self._records()
                page = self._page(records, self.root)
                pending = self.root / f".index-{uuid.uuid4().hex}.pending"
                pending.write_text(page, encoding="utf-8")
                pending.replace(self.root / "index.html")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            manifest["warnings"].append(f"Gallery generation failed; artifacts retained: {exc}")
            self._save(directory, manifest)
        return manifest

    def _records(self) -> tuple[list[dict], list[str]]:
        with _INDEX_LOCK:
            return self._records_unlocked()

    def _records_unlocked(self) -> tuple[list[dict], list[str]]:
        records, skipped = [], []
        if not self.root.exists():
            return records, skipped
        for directory in self.root.iterdir():
            if not directory.is_dir() or directory.is_symlink():
                continue
            try:
                _segment(directory.name)
                path = _within(directory, directory / "manifest.json")
                record = json.loads(_read(path))
                if (not isinstance(record, dict) or record.get("schema_version") != SCHEMA
                        or record.get("review_id") != directory.name
                        or any(not isinstance(record.get(key), str)
                               for key in ("label", "kind", "status", "created_utc",
                                           "artifact_dir", "manifest", "report"))):
                    raise ValueError("Legacy or invalid manifest")
                records.append(record)
            except (OSError, ValueError, KeyError):
                skipped.append(directory.name)
        records.sort(key=lambda m: m["review_id"], reverse=True)
        return records, skipped

    def history(self, limit: int = 20, before_id: str | None = None,
                label: str | None = None, kind: str | None = None) -> dict:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100.")
        if before_id is not None:
            _segment(before_id)
        if kind not in {None, "capture", "crop", "comparison"}:
            raise ValueError("kind must be capture, crop, or comparison.")
        records, skipped = self._records()
        filtered = [m for m in records if (before_id is None or m["review_id"] < before_id)
                    and (label is None or label.casefold() in m["label"].casefold())
                    and (kind is None or m["kind"] == kind)]
        page = filtered[:limit]
        # History is a compact index, not twenty copies of every artifact's metadata.
        # Full manifests are available via get() or the returned manifest path.
        summaries = []
        for record in page:
            keys = ("review_id", "kind", "status", "label", "view", "created_utc", "source",
                    "before_id", "after_id", "parent_review_id", "artifact_dir",
                    "manifest", "report", "elapsed_seconds", "warnings", "errors")
            summary = {key: record[key] for key in keys if key in record}
            summary["views"] = [view["name"] for view in record.get("views", [])]
            summaries.append(summary)
        return {"reviews": summaries, "next_before_id": page[-1]["review_id"] if len(filtered) > limit else None,
                "total": len(records), "skipped_legacy_or_invalid": skipped,
                "gallery": self.relative(self.root / "index.html")}

    def load(self, review_id: str) -> tuple[Path, dict]:
        if review_id == "latest":
            records, _ = self._records()
            latest = next((m for m in records if m["kind"] == "capture" and m["status"] == "ok"), None)
            if latest is None:
                raise ValueError("No successful capture exists in this project's history.")
            review_id = latest["review_id"]
        directory = _within(self.root, self.root / _segment(review_id))
        manifest_path = _within(directory, directory / "manifest.json")
        with _INDEX_LOCK:
            record = json.loads(_read(manifest_path))
        if (not isinstance(record, dict) or record.get("schema_version") != SCHEMA
                or record.get("review_id") != review_id):
            raise ValueError("Unsupported or mismatched review manifest.")
        return directory, record

    def _view(self, review_id: str, view: str) -> tuple[Path, dict, dict]:
        directory, record = self.load(review_id)
        selected = next((v for v in record.get("views", []) if v["name"] == view), None)
        if selected is None:
            raise ValueError(f"View {view!r} was not rendered in {record['review_id']}.")
        return directory, record, selected

    def capture(self, board_path: str | None = None, label: str = "",
                views: list[str] | None = None, width: int = 1600,
                layers: list[str] | None = None, mirror: bool = False,
                expected_sha256: str | None = None) -> dict:
        start = time.monotonic()
        _width(width)
        _label(label)
        specs = _views(views, layers, mirror)
        board = self.board_path(board_path)
        source = _read(board)
        source_hash = _sha(source)
        if expected_sha256 is not None and source_hash != expected_sha256.lower():
            raise ValueError("Saved board SHA-256 does not match expected_sha256; capture refused.")
        # Capture companion project settings/text variables before running any exporter.
        sources = {board: source}
        companion = board.with_suffix(".kicad_pro")
        if companion.exists():
            sources[_within(self.workspace, companion)] = _read(companion)
        directory, manifest = self._new("capture", label)
        manifest.update({
            "source": {"board_path": self.relative(board), "sha256": source_hash,
                       "state": "saved-file", "live_unsaved_changes": "not_inspected"},
            "render": {"width_px": width, "background": BACKGROUND, "padding_mm": PADDING_MM,
                       "palette": "isolated-kicad-default", "views_requested": list(specs),
                       "framing": "KiCad fit-page-to-board; viewBox is NOT absolute board coordinates"},
            "views": [],
        })
        original_hashes = {path: _sha(data) for path, data in sources.items()}
        try:
            snapshot_dir = directory / "source"
            snapshot_dir.mkdir()
            for path, data in sources.items():
                snapshot = snapshot_dir / path.name
                snapshot.write_bytes(data)
                manifest["artifacts"].append(self._artifact(directory, snapshot, role="source"))
            frozen = snapshot_dir / board.name
            # Exporters cannot pick up a user's changing color/theme preferences.
            config_dir = directory / "render-config"
            config_dir.mkdir()
            env = {**os.environ, "XDG_CONFIG_HOME": str(config_dir),
                   "KICAD_CONFIG_HOME": str(config_dir / "kicad")}
            manifest["render"]["kicad_version"] = _run([self.cli, "version"], 15, env)
            manifest["render"]["rsvg_version"] = _run(["rsvg-convert", "--version"], 15)
            self._save(directory, manifest)
            for name, spec in specs.items():
                try:
                    raw, svg, png = (directory / f"{name}{suffix}"
                                     for suffix in (".raw.svg", ".svg", ".png"))
                    args = [self.cli, "pcb", "export", "svg", "--mode-single",
                            "--layers", ",".join(spec["layers"]), "--output", str(raw),
                            "--fit-page-to-board", "--exclude-drawing-sheet", "--page-size-mode", "2"]
                    if spec["mirrored"]:
                        args.append("--mirror")
                    args.append(str(frozen))
                    _run(args, self.timeout, env)
                    root, box = _svg(raw)
                    # KiCad fits right to Edge.Cuts; padding keeps the outline and
                    # nearby connector labels from being clipped by the viewport.
                    box = [box[0] - PADDING_MM, box[1] - PADDING_MM,
                           box[2] + 2 * PADDING_MM, box[3] + 2 * PADDING_MM]
                    root.set("viewBox", " ".join(str(v) for v in box))
                    root.set("width", f"{box[2]}mm")
                    root.set("height", f"{box[3]}mm")
                    root.insert(0, ET.Element(f"{{{SVG_NS}}}rect", {
                        "x": str(box[0]), "y": str(box[1]), "width": str(box[2]),
                        "height": str(box[3]), "fill": BACKGROUND,
                    }))
                    ET.ElementTree(root).write(svg, encoding="utf-8", xml_declaration=True)
                    dimensions = _raster(svg, png, width, self.timeout)
                    artifacts = {
                        "raw_svg": self._artifact(directory, raw, role="native-export"),
                        "svg": self._artifact(directory, svg, role="view"),
                        "png": self._artifact(directory, png, role="view"),
                    }
                    manifest["views"].append({"name": name, **spec, **dimensions, **artifacts})
                    manifest["artifacts"].extend(artifacts.values())
                except (OSError, ValueError, RuntimeError, ET.ParseError,
                        subprocess.SubprocessError) as exc:
                    manifest["errors"].append({"view": name, "error": str(exc)})
                self._save(directory, manifest)
            manifest["status"] = ("ok" if len(manifest["views"]) == len(specs)
                                  else "partial" if manifest["views"] else "failure")
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            manifest["errors"].append({"error": str(exc)})
            manifest["status"] = "failure"
        changed = []
        for path, digest in original_hashes.items():
            try:
                if _sha(_read(path)) != digest:
                    changed.append(self.relative(path))
            except (OSError, ValueError):
                changed.append(self.relative(path))
        if companion not in sources and companion.exists():
            changed.append(self.relative(companion))
        manifest["source"]["changed_during_capture"] = changed
        if changed:
            manifest["warnings"].append("Source changed during capture. Images show the frozen snapshot, "
                                        "not the newest saved/live board. Capture again before approval.")
        # Record remnants too: failed exports and all diagnostic images are retained.
        known = {a["file"] for a in manifest["artifacts"]}
        for path in directory.iterdir():
            if path.suffix in {".svg", ".png"} and path.name not in known:
                manifest["artifacts"].append(self._artifact(directory, path, role="incomplete"))
        return self._finish(directory, manifest, start)

    def get(self, review_id: str = "latest", view: str = "top",
            crop: list[float] | None = None, width: int = 1600) -> dict:
        directory, record = self.load(review_id)
        if record["kind"] in {"crop", "comparison"}:
            if crop is not None:
                raise ValueError("For a new crop, use the original capture ID, not a derived review.")
            for artifact in record.get("images", []):
                self._verified(directory, artifact)
            return record
        directory, original, selected = self._view(review_id, view)
        if crop is None:
            self._verified(directory, selected["png"])
            return {**original, "images": [selected["png"]], "selected_view": view}
        _width(width)
        if (len(crop) != 4 or not all(math.isfinite(v) for v in crop)
                or crop[0] < 0 or crop[1] < 0 or crop[2] <= 0 or crop[3] <= 0
                or crop[0] + crop[2] > 1 or crop[1] + crop[3] > 1):
            raise ValueError("crop is normalized [left, top, width, height], within [0,1].")
        svg_source = self._verified(directory, selected["svg"])
        root, box = _svg(svg_source)
        cropped = [box[0] + crop[0] * box[2], box[1] + crop[1] * box[3],
                   crop[2] * box[2], crop[3] * box[3]]
        _dimensions(cropped, width)
        start = time.monotonic()
        target, manifest = self._new("crop", f"{view}-detail")
        manifest.update({"parent_review_id": original["review_id"], "source": original["source"],
                         "crop": crop, "view": view, "images": []})
        try:
            root.set("viewBox", " ".join(str(v) for v in cropped))
            root.set("width", f"{cropped[2]}mm")
            root.set("height", f"{cropped[3]}mm")
            svg, png = target / "detail.svg", target / "detail.png"
            ET.ElementTree(root).write(svg, encoding="utf-8", xml_declaration=True)
            manifest.update(_raster(svg, png, width, self.timeout))
            manifest["artifacts"] = [self._artifact(target, svg), self._artifact(target, png)]
            manifest["images"] = [manifest["artifacts"][1]]
            manifest["status"] = "ok"
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            manifest["status"] = "failure"
            manifest["errors"].append({"error": str(exc)})
        return self._finish(target, manifest, start)

    def compare(self, before_id: str, after_id: str = "latest", view: str = "top",
                label: str = "", width: int = 2400) -> dict:
        """Side-by-side visual comparison, deliberately not an unregistered pixel diff."""
        from PIL import Image, ImageDraw, ImageOps

        _width(width)
        _label(label)
        left_dir, left, left_view = self._view(before_id, view)
        right_dir, right, right_view = self._view(after_id, view)
        for key in ("layers", "mirrored"):
            if left_view[key] != right_view[key]:
                raise ValueError(f"Cannot compare views with different {key}.")
        paths = [self._verified(left_dir, left_view["png"]),
                 self._verified(right_dir, right_view["png"])]
        start = time.monotonic()
        directory, manifest = self._new("comparison", label or f"{view}-comparison")
        manifest.update({
            "before_id": left["review_id"], "after_id": right["review_id"], "view": view,
            "before_source": left["source"], "after_source": right["source"],
            "same_board_bytes": left["source"]["sha256"] == right["source"]["sha256"],
            "comparison": "side-by-side; each image independently fitted, NOT a registered pixel diff",
            "images": [],
        })
        if left["render"] != right["render"]:
            manifest["warnings"].append("Render settings differ; inspect source views before drawing conclusions.")
        try:
            cell_width, cell_height = width // 2, min(2400, width // 2)
            sheet = Image.new("RGB", (cell_width * 2, cell_height + 70), BACKGROUND)
            draw = ImageDraw.Draw(sheet)
            for index, (path, record, prefix) in enumerate(zip(paths, (left, right), ("BEFORE", "AFTER"))):
                with Image.open(path) as img:
                    image = ImageOps.contain(img.convert("RGB"), (cell_width - 16, cell_height))
                    sheet.paste(image, (index * cell_width + (cell_width - image.width) // 2, 70))
                caption = f"{prefix}  {record['source']['sha256'][:12]}"
                draw.text((index * cell_width + 12, 10), caption, fill="white", font_size=20)
                draw.text((index * cell_width + 12, 38), record["label"][:60],
                          fill="white", font_size=16)
            png = directory / "comparison.png"
            sheet.save(png)
            manifest["images"] = [self._artifact(directory, png)]
            manifest["artifacts"] = manifest["images"]
            manifest["status"] = "ok"
        except (OSError, ValueError) as exc:
            manifest["status"] = "failure"
            manifest["errors"].append({"error": str(exc)})
        return self._finish(directory, manifest, start)

    def _page(self, records: list[dict], base: Path) -> str:
        def link(path: str) -> str:
            target = _within(self.root, self.workspace / path)
            return html.escape(Path(os.path.relpath(target, base)).as_posix(), quote=True)

        cards = []
        for record in records:
            images = [(v["name"], v["png"], v["svg"]) for v in record.get("views", [])]
            images.extend((record["kind"], a, None) for a in record.get("images", []))
            figures = "".join(
                f'<figure><a href="{link(a["path"])}"><img loading="lazy" '
                f'src="{link(a["path"])}" alt="{html.escape(name, quote=True)}"></a>'
                f'<figcaption>{html.escape(name)}'
                + (f' · <a href="{link(svg["path"])}">SVG</a>' if svg else "")
                + '</figcaption></figure>' for name, a, svg in images
            )
            cards.append(
                f'<article><h2>{html.escape(record["label"] or record["kind"])}</h2>'
                f'<p>{html.escape(record["created_utc"])} · {html.escape(record["status"])} · '
                f'{html.escape(record.get("source", {}).get("sha256", "")[:12])}</p>'
                f'<a href="{link(record["manifest"])}">Manifest / source hashes</a> · '
                f'<a href="{link(record["report"])}">Review</a><div class="views">{figures}</div>'
                f'<p>{html.escape("; ".join(record.get("warnings", [])))}</p></article>'
            )
        return ('<!doctype html><html lang="en"><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width">'
                '<title>PCB review history</title><style>'
                'body{background:#101620;color:#e3eaf4;font:16px system-ui;margin:24px}'
                'a{color:#85c7ff}article{border-top:1px solid #445;padding:18px 0}'
                '.views{display:flex;flex-wrap:wrap;gap:12px}figure{margin:12px 0}'
                'img{width:480px;max-width:90vw;height:340px;object-fit:contain;background:#18202b}'
                'figcaption{padding:8px}p{color:#b9c9dc}</style>'
                '<h1>PCB review history</h1><p>Newest first. All captures, detail crops and comparisons '
                'are retained. Saved-file images exclude unsaved editor changes. Visual review is not DRC.</p>'
                + "".join(cards) + '</html>')


def register(mcp: Any) -> None:
    """Extend the existing pinned KiCad server; no second transport or board backend."""
    from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
    from ..config import get_config
    from .metadata import headless_compatible

    def store() -> ReviewStore:
        cfg = get_config()
        return ReviewStore(cfg.workspace, cfg.project_root, cfg.output_dir,
                           cfg.pcb_file, str(cfg.kicad_cli), cfg.cli_timeout)

    def result(repository: ReviewStore, record: dict, images: list[dict]) -> CallToolResult:
        # The text fallback contains the same usable metadata, never opaque base64.
        content: list[Any] = []
        image_blocks, used = [], 0
        for artifact in images:
            directory = _within(repository.root, repository.workspace / record["artifact_dir"])
            path = repository._verified(directory, artifact)
            data = _read(path)
            if used + len(data) > MAX_IMAGE_BYTES:
                record = {**record, "response_warning": "Inline image budget exceeded; "
                          "all images retained. Request one view with pcb_visual_get."}
                break
            used += len(data)
            image_blocks.extend([
                TextContent(type="text", text=f"Image: {artifact['path']}"),
                ImageContent(type="image", mimeType="image/png",
                             data=base64.b64encode(data).decode("ascii")),
            ])
        content.append(TextContent(type="text", text=json.dumps(record, indent=2)))
        content.extend(image_blocks)
        return CallToolResult(content=content, structuredContent=record,
                              isError=record.get("status") in {"partial", "failure"})

    export = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                             idempotentHint=False, openWorldHint=False)
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                           idempotentHint=True, openWorldHint=False)

    @mcp.tool(annotations=export)
    @headless_compatible
    def pcb_visual_review(
        board_path: str | None = None, label: str = "", views: list[str] | None = None,
        width: int = 1600, layers: list[str] | None = None, mirror: bool = False,
        expected_sha256: str | None = None, include_images: bool = True,
    ) -> CallToolResult:
        """Capture a saved PCB as persistent SVG + PNG views and return native MCP images.

        Uses frozen copies and KiCad CLI, NOT unsaved GUI state. Explicitly pcb_save first
        for live edits. Never saves/refills/promotes the source. Retains every run under
        the ACTIVE project's output/image-review, including candidate captures.
        board_path: absolute /workspace path or workspace-relative; omit for active PCB.
        views: top/bottom (default), assembly_top/assembly_bottom, copper_top/copper_bottom,
        or ['all']. Bottom views are mirrored (viewed from underside). Alternatively use
        canonical custom layers, e.g. ['In1.Cu','Edge.Cuts'], and optional mirror.
        width: 400–6000 pixels, subject to a 16MP/6000px edge cap. expected_sha256 pins
        candidate identity. include_images=false returns metadata only (images still saved).
        Use pcb_visual_history, pcb_visual_get (detail crops), and pcb_visual_compare next.
        """
        repository = store()
        record = repository.capture(board_path, label, views, width, layers, mirror, expected_sha256)
        return result(repository, record, [v["png"] for v in record["views"]] if include_images else [])

    @mcp.tool(annotations=read)
    @headless_compatible
    def pcb_visual_history(limit: int = 20, before_id: str | None = None,
                           label: str | None = None, kind: str | None = None) -> CallToolResult:
        """List retained reviews newest-first in the active project, without returning images.

        Includes source hashes, labels, paths, errors, and gallery HTML path. limit 1–100;
        pass next_before_id back as before_id for stable pagination. Optional label
        substring and kind capture/crop/comparison filters. Never deletes/prunes history.
        """
        repository = store()
        return result(repository, repository.history(limit, before_id, label, kind), [])

    @mcp.tool(annotations=export)
    @headless_compatible
    def pcb_visual_get(review_id: str = "latest", view: str = "top",
                       crop: list[float] | None = None, width: int = 1600) -> CallToolResult:
        """Return a retained PNG immediately, or persist a sharp detail crop from its SVG.

        review_id is any retained review ID or 'latest' successful capture. A crop/comparison
        ID returns its saved image directly (view/width ignored; no nested cropping).
        For capture IDs, crop is normalized
        [left,top,width,height] in the displayed image, within [0,1], NOT PCB millimeters.
        Example [0.25,0.25,0.5,0.5] zooms the center half. Bottom coordinates follow the
        mirrored image. Crops rerasterize retained vectors, never re-export the board.
        width controls crops only; omit crop to get the original full-resolution PNG.
        """
        repository = store()
        record = repository.get(review_id, view, crop, width)
        return result(repository, record, record.get("images", []))

    @mcp.tool(annotations=export)
    @headless_compatible
    def pcb_visual_compare(before_id: str, after_id: str = "latest", view: str = "top",
                           label: str = "", width: int = 2400) -> CallToolResult:
        """Persist and return a labeled before/after contact sheet from two retained captures.

        No KiCad export is run. Layers and orientation must match. Images are independently
        fitted side-by-side, NOT geometrically registered; this is not a pixel-diff metric
        or electrical correctness verdict. Retrieve originals/crops for fine details.
        Source hashes, review IDs and differing render settings are reported and retained.
        """
        repository = store()
        record = repository.compare(before_id, after_id, view, label, width)
        return result(repository, record, record.get("images", []))
