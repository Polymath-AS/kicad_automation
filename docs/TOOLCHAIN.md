# Toolchain

Required authority split:

| Area | Authority |
|---|---|
| Codex-facing EDA tools | `kicad-mcp-pro` |
| Live PCB inspection and mutation | KiCad 10 IPC through MCP Pro / `kipy` |
| Placement/routing candidates | Pinned KiCadRoutingTools service on read-only source copies |
| Reviewed candidate promotion | Repository transaction adapters over MCP Pro live IPC |
| Schematic operations | MCP Pro schematic tools; file-backed operations are explicit structured S-expression edits |
| ERC, DRC, parity checks | `kicad-cli` |
| Gerbers, drills, PDFs, manufacturing outputs | `kicad-cli` and the bundled `kicad10_auto` tools |

The Docker image pins `ghcr.io/inti-cmnb/kicad10_auto:1.9.0` and `kicad-mcp-pro==3.34.0`. KiCad `10.0.4` is acceptable here because the target is a stable KiCad 10 IPC runtime with bundled automation tools, not the latest KiCad patch.

SWIG `pcbnew` is not an editing backend in this repository. A missing or failed IPC operation is a tool failure, not a reason to load `pcbnew` silently.

Use the same workflow for automated edits:

```text
inspect through MCP Pro
edit through IPC-backed MCP Pro tools where supported
generate placement/routing candidates in isolated KiCadRoutingTools jobs
promote only reviewed supported deltas through verified transaction adapters
save through MCP Pro
validate/export with kicad-cli
```

KiCad 10 GUI IPC cannot be assumed until the integration test proves it. The test must start Xvfb, launch `pcbnew`, observe the IPC socket, start MCP Pro, list MCP tools, and call an IPC-required PCB query.
