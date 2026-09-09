import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class KicadMcpCompatibilityPatchTests(unittest.TestCase):
    def test_pad_lookup_patch_is_version_pinned_and_build_verified(self):
        dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
        patch = (
            ROOT / "docker" / "patches" / "kicad-mcp-pro-3.34.0-kicad10-pad-lookup.patch"
        ).read_text(encoding="utf-8")
        self.assertIn("ARG KICAD_MCP_PRO_VERSION=3.34.0", dockerfile)
        self.assertIn("kicad-mcp-pro-3.34.0-kicad10-pad-lookup.patch", dockerfile)
        self.assertIn("verify_kicad_mcp_compat.py", dockerfile)
        self.assertIn("board_footprints", patch)
        self.assertNotIn("pad.parent.reference_field", patch.split("+    #", 1)[-1])


if __name__ == "__main__":
    unittest.main()
