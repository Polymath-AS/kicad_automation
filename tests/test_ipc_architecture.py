import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ArchitectureTests(unittest.TestCase):
    def test_no_repo_owned_mcp_or_pcb_backend_remains(self):
        removed = [
            ROOT / "docker" / "eda",
            ROOT / "docker" / "bin" / "eda-cli",
            ROOT / "docker" / "bin" / "eda-mcp",
            ROOT / "docker" / "bin" / "kicad-board",
            ROOT / "docker" / "bin" / "kicad-toolchain",
        ]
        self.assertEqual([p.relative_to(ROOT).as_posix() for p in removed if p.exists()], [])

    def test_active_runtime_does_not_import_swig_pcbnew(self):
        active = [ROOT / "docker" / "bin", ROOT / "scripts", ROOT / "tools"]
        needles = ["import pcbnew", "pcbnew.LoadBoard", "pcbnew.SaveBoard"]
        offenders = []
        for root in active:
            for path in root.rglob("*"):
                if path.is_file() and path.suffix in {"", ".py", ".ps1", ".sh"}:
                    text = path.read_text(encoding="utf-8")
                    if any(needle in text for needle in needles):
                        offenders.append(path.relative_to(ROOT).as_posix())
        self.assertEqual(offenders, [])

    def test_dockerfile_uses_pinned_kicad_auto_and_mcp_pro(self):
        dockerfile = (ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn(
            "FROM ghcr.io/inti-cmnb/kicad10_auto:1.9.0@sha256:493666a06d900ed3352c50b0f75a76ccdfe194999c097d455021cab9e3c723fa",
            dockerfile,
        )
        self.assertIn("ARG KICAD_MCP_PRO_VERSION=3.34.0", dockerfile)
        self.assertIn("kicad-mcp-pro[http]==${KICAD_MCP_PRO_VERSION}", dockerfile)

    def test_compose_exposes_mcp_on_loopback_only(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        self.assertIn("127.0.0.1:${KICAD_MCP_PORT:-3334}:3334", compose)
        self.assertNotIn("network_mode: none", compose)

    def test_codex_mcp_config_is_clone_safe_and_focused(self):
        config = (ROOT / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.assertIn('[mcp_servers.kicad]', config)
        self.assertIn('url = "http://127.0.0.1:3334/mcp"', config)
        self.assertIn(
            'http_headers = { Authorization = "Bearer '
            'kicad-automation-local-dev-token-change-me-2026" }',
            config,
        )
        self.assertNotIn("bearer_token_env_var", config)
        self.assertIn("required = false", config)
        self.assertIn("startup_timeout_sec = 60", config)
        self.assertIn('"pcb_get_board_summary"', config)


if __name__ == "__main__":
    unittest.main()
