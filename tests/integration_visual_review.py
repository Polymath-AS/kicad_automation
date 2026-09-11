"""Exercise the actual HTTP MCP/CLI/raster pipeline; never mutate the input board."""

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from kicad_mcp_client import DEFAULT_TOKEN, DEFAULT_URL, request


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("KICAD_MCP_URL", DEFAULT_URL))
    parser.add_argument("--token", default=os.environ.get("KICAD_MCP_AUTH_TOKEN", DEFAULT_TOKEN))
    parser.add_argument("--board", type=Path, required=True)
    args = parser.parse_args()
    source_hash = digest(args.board)
    project_file = args.board.with_suffix(".kicad_pro")
    project_hash = digest(project_file) if project_file.exists() else None
    label = f"integration-{time.time_ns()}"
    started = time.monotonic()
    timings = {}

    def call(name, arguments, images=None, error=False):
        start = time.monotonic()
        result = request(args.url, args.token, "tools/call",
                         {"name": name, "arguments": arguments}, 120)["result"]
        timings.setdefault(name, []).append(round(time.monotonic() - start, 3))
        if error:
            assert result.get("isError"), result
            return result
        assert not result.get("isError"), result.get("content")
        record = result.get("structuredContent")
        assert isinstance(record, dict), result.keys()
        if images is not None:
            blocks = [c for c in result["content"] if c["type"] == "image"]
            assert len(blocks) == images, (name, len(blocks), images)
            for block in blocks:
                assert block["mimeType"] == "image/png"
                assert base64.b64decode(block["data"]).startswith(b"\x89PNG\r\n\x1a\n")
        return record

    # Check raw discovery, not the client's synthetic stable-tool catalog.
    tools = request(args.url, args.token, "tools/list", {}, 30)["result"]["tools"]
    names = {t["name"] for t in tools}
    required = {"pcb_visual_review", "pcb_visual_get", "pcb_visual_history", "pcb_visual_compare"}
    assert required <= names, required - names
    first = call("pcb_visual_review", {
        "board_path": str(args.board), "expected_sha256": source_hash,
        "label": f"{label}-before", "width": 800,
        "views": ["top", "bottom", "assembly_top", "assembly_bottom"],
    }, images=4)
    assert first["status"] == "ok", first
    assert first["source"]["sha256"] == source_hash
    assert first["source"]["changed_during_capture"] == []
    directory = Path("/workspace") / first["artifact_dir"]
    before_files = {p: digest(p) for p in directory.rglob("*") if p.is_file()}
    for artifact in first["artifacts"]:
        assert digest(directory / artifact["file"]) == artifact["sha256"], artifact
    for view in first["views"]:
        assert view["width_px"] == 800
    second = call("pcb_visual_review", {
        "board_path": str(args.board), "label": f"{label}-after", "width": 800,
        "expected_sha256": source_hash, "include_images": False,
    }, images=0)
    assert first["review_id"] != second["review_id"]
    assert first["source"]["sha256"] == second["source"]["sha256"]
    # The same saved state under isolated rendering settings must yield the same pixels.
    assert first["views"][0]["png"]["sha256"] == second["views"][0]["png"]["sha256"]
    retrieved = call("pcb_visual_get", {"review_id": first["review_id"], "view": "top"}, images=1)
    assert retrieved["images"][0] == first["views"][0]["png"]
    crop = call("pcb_visual_get", {
        "review_id": first["review_id"], "view": "top",
        "crop": [0.25, 0.25, 0.5, 0.5], "width": 1200,
    }, images=1)
    assert crop["kind"] == "crop" and crop["width_px"] == 1200
    compared = call("pcb_visual_compare", {
        "before_id": first["review_id"], "after_id": second["review_id"],
        "label": f"{label}-compare", "width": 1200,
    }, images=1)
    assert compared["same_board_bytes"]
    for derived in (crop, compared):
        cached = call("pcb_visual_get", {"review_id": derived["review_id"]}, images=1)
        assert cached["images"] == derived["images"]
    history = call("pcb_visual_history", {"label": label, "kind": "capture", "limit": 1})
    assert history["reviews"][0]["review_id"] == second["review_id"]
    page = call("pcb_visual_history", {
        "label": label, "kind": "capture", "limit": 1, "before_id": history["next_before_id"],
    })
    assert page["reviews"][0]["review_id"] == first["review_id"]
    call("pcb_visual_review", {"expected_sha256": "0" * 64}, error=True)
    call("pcb_visual_review", {"board_path": "/etc/passwd"}, error=True)
    call("pcb_visual_get", {"review_id": "../outside"}, error=True)
    call("pcb_visual_get", {"review_id": first["review_id"], "crop": [0, 0, 2, 1]}, error=True)
    for path, expected in before_files.items():
        assert digest(path) == expected, f"Earlier artifact was changed: {path}"
    assert digest(args.board) == source_hash, "Source PCB was modified"
    if project_hash:
        assert digest(project_file) == project_hash, "Source project was modified"
    assert (Path("/workspace") / first["gallery"]).is_file()
    print(json.dumps({
        "status": "ok", "transport": "real HTTP MCP", "source_sha256": source_hash,
        "source_unchanged": True, "previous_artifacts_unchanged": True,
        "captures": [first["review_id"], second["review_id"]],
        "crop": crop["review_id"], "comparison": compared["review_id"],
        "gallery": first["gallery"], "timings_seconds": timings,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }, indent=2))


if __name__ == "__main__":
    main()
