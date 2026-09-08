# Pending MCP changes

Status: implementation complete for the verified KiCad 10.0.4/MCP Pro 3.34.0 stack; live schematic IPC remains unsupported by that stack.
Recorded: 2026-09-08.

## Objective

Determine whether the installed KiCad/MCP stack supports live schematic access, enable it if supported, and make project selection and validation failures easy to diagnose. Preserve the working PCB IPC workflow.

This document is an implementation handoff for a lower-tier model. Work through the tasks in order. Do not interpret proposed configuration names or operations as existing APIs.

## Verified baseline

- Live MCP calls succeeded: server info, version, project info, board summary, footprints, and nets.
- Server: KiCad MCP Pro 3.34.0; KiCad CLI/IPC 10.0.4; IPC API 10.0.1.
- Server reports `livePcbContext: true`, `liveSchematicContext: false`, and write operating mode.
- Active server project: `/workspace/linear_regulator_test/linear_regulator_test.kicad_pro`.
- Live board: zero footprints, tracks, vias, zones, and shapes; one unnamed net.
- Server reports schematic live writes unavailable because they require an open schematic document. This message alone does not prove that opening Eeschema will provide a supported schematic IPC API.
- `docker/bin/kicad-runtime` starts only `pcbnew` in its normal serve path. Readiness checks call `get_version()` and `get_board()`.
- `compose.yaml`, `docker/Dockerfile`, and the runtime default to `KICAD_MCP_PROFILE=pcb_only`.
- `docker/bin/run-kicad-integration-tests` briefly starts Eeschema after validation, but checks only process survival. It does not prove live schematic MCP access.
- The active server project directory was absent from the local repository workspace. Its actual host mount has not been determined.
- Repository validation initially failed with Docker named-pipe access denied. An elevated retry reached Compose but failed with exit code 2 and no useful underlying diagnostic in the returned output. ERC/DRC results remain unknown.
- No design edits or save operation were tested in this session.

## Support investigation and implementation evidence

The installed package and runtime were inspected before changing startup. The relevant source
locations are:

- MCP Pro 3.34.0: `/opt/kicad-mcp-pro/lib/python3.13/site-packages/kicad_mcp/`.
  `ipc/capabilities.py` gates live schematic access on KiCad major version 10+ and
  `active_client.has_open_schematic()`. `ipc/client.py` implements that probe with
  `get_open_documents(DOCTYPE_SCHEMATIC)` and returns false on probe errors.
- MCP Pro endpoint selection: `ipc/discovery.py` resolves one configured or environment
  endpoint, normally `KICAD_API_SOCKET`; `ipc/runtime_probe.py` queries PCB and schematic
  document counts through that same client. No second schematic socket is defined.
- KiCad IPC Python binding: `/opt/kicad-mcp-pro/lib/python3.13/site-packages/kipy/kicad.py`
  exposes `get_open_documents()`, `get_project()`, and `get_board()`. The installed
  `kipy/schematic.py` declares its `Schematic` class `versionadded: 0.7.0 (KiCad 11)` and
  cannot import against the bundled KiCad 10 generated protobufs (`BusEntryType` is missing).
- MCP Pro profile routing: `kicad_mcp/tools/router.py` maps `schematic_only` to the project,
  schematic, and library categories; `pcb_only` does not include the schematic category.
  `kicad_mcp/tools/schematic_inspection.py` and `kicad_mcp/tools/schematic.py` identify the
  legacy `sch_get_*` inspection path as parser/file-backed and report `Source: file-backed`.
  The capability registry separately marks live-required schematic operations as IPC-gated.

| Question | Verified result | Classification |
| --- | --- | --- |
| KiCad 10.0.4 schematic API | The official IPC documentation says KiCad 9/10 IPC communicates with a running GUI and is PCB-oriented; schematic-editor support is future-facing. The installed binding's schematic class is KiCad 11-only and import-incompatible with the bundled KiCad 10 protos. | API support: not verified; do not claim live schematic IPC |
| Live-context detection | MCP Pro probes `GetOpenDocuments(DOCTYPE_SCHEMATIC)` over the configured `KICAD_API_SOCKET`; the current server reports `liveSchematicContext: false`. | Open-document state: false |
| Profiles and allowlists | `pcb_only` preserves the current live PCB tools. `schematic_only` exposes the schematic category, including file-backed reads; runtime IPC filtering hides IPC-required tools when no live schematic is present. | Tool exposure: profile-dependent |
| Simultaneous PCB/schematic connections | No supported second endpoint or KiCad 10 schematic IPC surface was found. The runtime has one dedicated PCB socket and does not start Eeschema. | Unsupported by installed stack |
| Schematic operations | Legacy `sch_get_symbols`, `sch_get_wires`, `sch_get_labels`, and related inspection paths parse `.kicad_sch` files. IPC-gated operations are only discoverable when their live capability is present. | File-backed versus live IPC: explicitly separated |

The official reference used for the API decision is the KiCad developer documentation:
https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/

The running container was also inspected read-only. Its bind mount is
`C:\Users\fnk\Documents\KiCad\Projects\kicad_automation -> /workspace`, while its command
was `serve linear_regulator_test/linear_regulator_test.kicad_pcb`. That selected directory is not
present under `/workspace`, although the already-running GUI/MCP session still reports it. The
implementation treats this as a host/container selection mismatch and fails before starting or
validating a missing target; it does not recreate the project.

Implemented changes:

- Added explicit `KICAD_MCP_SCHEMATIC_MODE=disabled|file_backed|live`. The default remains
  PCB-only; `live` fails clearly because the installed stack cannot support it.
- Updated `.codex/config.toml` with the supported file-backed schematic inspection tools. Live
  schematic writes were not added to the client allowlist because their IPC capability is false.
- Added host and container project preflight for matching `.kicad_pro`, `.kicad_sch`, and
  `.kicad_pcb` files, including the resolved host path and `/workspace` container path.
- Changed validation to preserve the KiCad CLI log, report paths, ERC/DRC counts, exit codes,
  and distinct `clean`, `violations`, and `error` statuses. The PowerShell wrapper preserves
  sanitized Compose failures under `.kicad-automation/compose-failures/`.
- Reworked integration coverage to assert live PCB reads before and after save, record schematic
  capability/backend evidence, reject a file-backed result when live schematic mode is expected,
  and require explicit clean ERC and DRC results. Eeschema process survival is no longer treated
  as schematic IPC evidence.

Verification completed:

- `python -m unittest discover -s tests -v`: 8 tests passed.
- Rebuilt the pinned image successfully.
- Valid target: `tools/kicad-docker.ps1 validate tests/fixtures/kicad-project/minimal --erc --drc`
  returned `status=clean`; ERC and DRC each returned `status=pass`, exit code 0, report present,
  and violation count 0.
- Missing target preflight returned the host path, `/workspace` path, and all three missing
  project files before Docker started.
- Non-elevated Docker access failure was classified as `docker_access_or_connectivity` and its
  sanitized output was written under `.kicad-automation/compose-failures/`.
- Default `pcb_only` integration passed with live PCB summaries before and after `pcb_save`, no
  live schematic context, and clean ERC/DRC.
- Combined `default` profile with `KICAD_MCP_SCHEMATIC_MODE=file_backed` passed with
  `schematic_tool_exposed=1`, a real `.kicad_sch` read labeled `Source: file-backed`,
  `liveSchematicContext=false`, and live PCB checks intact.
- `schematic_only` plus `file_backed` passed its schematic read and validation path. The
  profile correctly exposed no PCB tool, so the integration test records that distinction.
- `KICAD_MCP_SCHEMATIC_MODE=live` failed before editor startup with the documented KiCad
  10.0.4 limitation. No live schematic write or save was claimed.

## Task 1 — Verify schematic support before changing startup

Inspect only the installed MCP package, its relevant documentation, and the official KiCad API documentation needed for this question. Record exact package versions and source locations. Verify:

1. Whether KiCad 10.0.4 exposes the schematic document operations the MCP server requires.
2. How MCP Pro 3.34.0 detects a live schematic context and selects its IPC endpoint.
3. Which supported profile exposes schematic tools, and whether the client tool allowlist also needs updating.
4. Whether simultaneous PCB and schematic connections are supported, and how their sockets are configured.
5. Which schematic operations are truly live IPC operations versus guarded file-backed operations.

Acceptance: add a short evidence-backed support matrix to this document. Distinguish API support, open-document state, tool exposure, and file-backed features.

If the installed stack cannot support live schematic access, document that limitation and the verified prerequisite version/configuration. Do not invent an API, silently upgrade dependencies, or claim that file-backed editing is live access. Complete the independent diagnostics tasks below.

## Task 2 — Add optional schematic startup, only if Task 1 proves support

Likely files: `docker/bin/kicad-runtime`, `compose.yaml`, `.env.example`, and `README.md`. Change `docker/Dockerfile` only if verified dependencies require it.

- Keep the existing PCB-only default working. Add an explicit, documented opt-in for schematic access using configuration supported by the installed server.
- Resolve the schematic from the selected project stem and verify it exists before launching.
- Start Eeschema with a dedicated log and tracked process ID; include it in shutdown and early-exit handling.
- Use the verified endpoint scheme. Do not let PCB startup's socket cleanup remove a running schematic socket.
- Handle first-run dialogs where needed. A running process or visible window is not sufficient readiness evidence.
- Probe the actual schematic document through supported MCP/IPC operations, with bounded retries and actionable errors.
- Recheck PCB reads after enabling schematic access to catch endpoint regressions.

Acceptance: both document contexts are demonstrated through real supported calls, or schematic enablement fails clearly while the documented PCB-only mode remains usable.

## Task 3 — Resolve host/container project mismatch

Likely files: `tools/kicad-docker.ps1`, runtime diagnostics, and `README.md`.

1. Inspect the running service's mount source and selected board without dumping secrets or complete environment variables.
2. Compare the active MCP paths against that mount and the PowerShell wrapper's `ProjectRoot`.
3. Determine whether the discrepancy is a different mount, stale server selection, or another cause. Record evidence; do not assume the project was deleted.
4. Add focused preflight checks for the selected project and required files. Explain the expected host path and container path when they differ.
5. Document how to run validation against the same host root as the live service.

Acceptance: a valid target resolves consistently across host, container, and MCP. A missing target produces a specific error before validation runs. Do not overwrite or recreate the missing project to mask the mismatch.

## Task 4 — Preserve validation diagnostics

Likely files: `tools/kicad-docker.ps1`, `docker/bin/validate-kicad`, and relevant tests.

- Investigate why the elevated validation returned only a generic Compose failure.
- Preserve the underlying validator stdout/stderr and exit status in a useful error report.
- Distinguish Docker access/connectivity failures, missing project files, validator execution errors, and reported ERC/DRC violations.
- Report generated report paths and violation counts when available. Never label a failed or skipped validator as a clean design.
- Avoid printing authentication tokens.

Acceptance: deliberately missing target and valid target cases return clear, different outcomes. ERC and DRC each have an explicit result or a specific reason they could not run.

## Task 5 — Extend integration coverage and usage notes

Likely file: `docker/bin/run-kicad-integration-tests` and existing relevant tests.

- Retain the PCB live-source assertion.
- For the optional schematic mode, verify tool exposure and a real document read through the supported backend; reject unexpected file-backed fallback when testing live access.
- Cover unsupported schematic capability, missing schematic file, and editor startup failure with bounded failures and useful log paths.
- Use an isolated small test project for any mutation/save test; do not mutate the user's active project or a shared fixture in place.
- If a new project is needed, create it with `kicad_create_new_project` while the server has an existing board open, then restart against the generated board.
- After every design mutation run the repository validation command below. Verify saving and reopen/readback separately from the mutation result.
- Update README with supported modes, startup commands, limitations, and troubleshooting paths verified during implementation.

```powershell
.\tools\kicad-docker.ps1 validate <project-stem> --erc --drc
```

Acceptance: report live server state, board summary, schematic capability evidence, files changed, save/readback results if tested, and separate ERC/DRC outcomes. Do not claim end-to-end write support from read-only probes.

## Implementation guardrails

- Follow `AGENTS.md`. Before EDA edits, call `kicad_get_server_info`, `kicad_get_project_info`, and `pcb_get_board_summary`.
- Use MCP Pro IPC-backed tools for PCB edits and saving. Never use `pcbnew` SWIG or direct board/project file edits as a fallback.
- If MCP is unavailable, diagnose it and stop before design changes.
- Read relevant target files only; avoid scanning `references/` or historical analyses.
- Keep infrastructure changes separate from test-design mutations. Do not change dependencies unless evidence requires it and the change is explicitly identified.
- Check actual tool schemas before calls. Tools advertised by server capability metadata may not be exposed to the current client.

## Ready-to-use implementation prompt

> Implement the pending tasks in `docs/pending-mcp-changes.md`, following `AGENTS.md`. Start with the schematic support investigation and record evidence before changing startup. Preserve PCB-only behavior. If live schematic IPC is unsupported, document the precise limitation and complete the independent project-path and validation-diagnostics fixes. Use small scoped changes and meaningful integration checks. Do not claim success for untested writes, file-backed substitutes, or skipped ERC/DRC. Finish with files changed, test results, and remaining blockers.
