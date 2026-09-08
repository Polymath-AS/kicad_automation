# Turnkey Docker toolchain

The Windows KiCad GUI remains the interactive editor. Docker provides a pinned, headless worker for checks, fabrication outputs, renders and board utilities, plus a separately pinned Freerouting worker. The KiCad worker is based on `ghcr.io/inti-cmnb/kicad9_auto:1.9.0`, which contains KiCad 9.0.7, KiBot 1.9.0, KiAuto, InteractiveHtmlBom, KiDiff and KiKit. Freerouting is pinned to 2.4.1.

Docker Desktop must be running with Linux containers enabled. In PowerShell from this repository:

```powershell
# Build images and verify every expected executable.
.\tools\kicad-docker.ps1 smoke

# Check another repository. The target is relative to ProjectRoot.
.\tools\kicad-docker.ps1 check CAD/my-board/my-board -ProjectRoot C:\path\to\project

# Run a project-owned KiBot configuration.
.\tools\kicad-docker.ps1 kibot automation/release.kibot.yaml CAD/my-board/my-board.kicad_pro -ProjectRoot C:\path\to\project

# Produce an interactive BOM.
.\tools\kicad-docker.ps1 ibom CAD/my-board/my-board.kicad_pcb -ProjectRoot C:\path\to\project

# Route an existing DSN into the matching SES file.
.\tools\kicad-docker.ps1 route .kicad-automation/router/candidate.dsn -ProjectRoot C:\path\to\project

# Bound a larger routing attempt explicitly.
.\tools\kicad-docker.ps1 route .kicad-automation/router/candidate.dsn .kicad-automation/router/candidate.ses -MaxPasses 30 -ProjectRoot C:\path\to\project

# Enable two optimization threads and impose a ten-minute wall-clock limit.
.\tools\kicad-docker.ps1 route .kicad-automation/router/candidate.dsn .kicad-automation/router/optimized.ses -MaxPasses 30 -OptimizerThreads 2 -TimeoutSeconds 600 -ProjectRoot C:\path\to\project
```

`check` writes JSON reports under `.kicad-automation/reports` inside the mounted project and returns compact summaries. DRC/ERC violations produce a failing command. `route` accepts only project-relative paths and writes the SES beside the DSN unless an explicit output path is supplied. Routing defaults to no optimization (`-OptimizerThreads 0`) and a five-minute wall-clock limit, so a bounded job cannot consume a worker indefinitely. Use a fresh SES path for every attempt; the wrapper refuses to overwrite prior evidence.

The KiCad worker has networking disabled during normal runs. Image builds and pulls require network access. Freerouting also runs without network access and analytics is disabled. The project directory is bind-mounted read/write because checks create reports and export commands create artifacts. Keep the board closed in the GUI while promoting container-generated source edits; the supplied commands currently check/export and do not directly modify the PCB or schematic.

The wrapper uses a task-specific Docker configuration directory under `%TEMP%` so a restricted automation account does not need to read the user's Docker client configuration. It does not start Docker Desktop. If Docker reports that the daemon is unavailable or access is denied, start Docker Desktop under the current Windows account and confirm `docker version` works before rerunning `smoke`.

Both upstream images are pinned by a readable version tag and an immutable digest. To audit the local copies:

```powershell
docker image inspect local/kicad-automation:9.0.7-1 --format '{{index .RepoDigests 0}}'
docker image inspect ghcr.io/freerouting/freerouting:2.4.1 --format '{{index .RepoDigests 0}}'
```

Changing a version requires updating and verifying the digest in `docker/Dockerfile`, `compose.yaml`, and `.env.example`, then rerunning the smoke test.

Windows-host bind mounts are convenient for live GUI work but can be slower than Linux-native storage. KiCad projects are usually small enough for checks and exports; measure before moving repositories. Docker recommends Linux-filesystem storage when WSL bind-mount performance becomes material.

## Current boundary

This environment contains the complete headless toolchain. A broad KiCad MCP is not bundled yet because it needs a tested client configuration and, for live IPC on KiCad 9, access to the running Windows GUI's named pipe. The next layer should expose four compact operations—inspect, check, route and release—around these containers. Keeping that interface separate lets us validate the deterministic worker before introducing a large tool schema.
