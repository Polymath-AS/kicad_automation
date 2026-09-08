# KiCad tools and plugins to prepare

Research checked 2026-09-08. Pin the versions that pass a small end-to-end smoke test; an older working design should not be migrated solely to obtain a newer plugin.

For specific MCP candidates and a phase-based savings scenario, see [MCP evaluation](MCP_EVALUATION.md).

## Prepare first

| Tool | Installation/preparation | Why it matters here |
|---|---|---|
| KiCad, official symbol and footprint libraries | Install one chosen version with its libraries; record explicit CLI and library paths | Missing footprints and mixed library locations interrupted the source session |
| `kicad-cli` | Included with KiCad; verify JSON ERC/DRC, parity checks and violation exit codes | A deterministic check/export interface avoids GUI and large report conversations |
| KiCad's bundled Python / `pcbnew` | Use the executable from the same installation for the existing scripts | System Python and version-dependent API assumptions caused failures |
| Freerouting KiCad plugin | KiCad Manager → Tools → Plugin and Content Manager → search Freerouting → Install; reopen PCB Editor and test it | Automates ordinary routing through the DSN/SES workflow |
| Compatible Java runtime, if using a JAR | Match the selected Freerouting release and record its absolute path | The session initially used Java 8 against a Java 17 build |
| Git and ordinary Python | Verify repository access and the executable once | Milestones and portable report/verification helpers |
| Export/render dependencies | Use native KiCad exports; verify a PDF renderer such as Poppler or a project-pinned PDFium helper, plus any SVG converter the pipeline actually invokes | Missing rendering tools and export flag errors consumed finalization work |

The [KiCad CLI manual](https://docs.kicad.org/9.0/en/cli/cli.html) documents JSON checks and `--exit-code-violations` (0 clean, 5 violations). The [Freerouting integration instructions](https://github.com/freerouting/freerouting/blob/master/integrations/KiCad/README.md) document PCM installation and DSN as the default/recommended mode. Its newer JSON/API mode is experimental and does not cover all KiCad rules, including copper-to-edge clearance; keep native DRC after import.

## Java and API compatibility

The observed baseline is **KiCad 9.0.7 + Freerouting 1.6.2 + Java 17**. In that session, the old optimizer stalled with two threads and completed with `-mt 1`; `-Djava.awt.headless=true` also failed with that old GUI-dependent router. Preserve these as legacy compatibility facts, not global defaults.

The current upstream [Freerouting README](https://github.com/freerouting/freerouting/blob/master/README.md#running-freerouting-using-java-jre) instructs JAR users to select **Java 25** and also lists native installers. Therefore, do not pair a newly downloaded JAR with the old Java 17 command without checking that release's requirements. Choose one tested combination and save it in the toolchain record.

KiCad's legacy SWIG Python bindings are deprecated. The official [API overview](https://dev-docs.kicad.org/en/apis-and-binding/) and [IPC guidance](https://dev-docs.kicad.org/en/apis-and-binding/ipc-api/for-addon-developers/) recommend the IPC API for new integrations. In KiCad 9 and 10 it communicates with a running GUI; the documentation places CLI headless server support in KiCad 11. Keep the existing 9.0.7 scripts pinned while building an adapter for a newer interface; IPC is not a drop-in replacement for `pcbnew.LoadBoard()`.

## Optional additions, in order of relevance

| Addition | Recommendation | Qualification |
|---|---|---|
| [Freerouting's official local MCP integration](https://github.com/freerouting/freerouting/blob/master/docs/API/MCP.md) | Benchmark next if upgrading the routing engine | Documents `autoroute_board` with file paths, bounded execution, SES and diagnostic output; could collapse several conversational steps into one. Not exercised in this analysis |
| [InteractiveHtmlBom](https://github.com/openscopeproject/InteractiveHtmlBom) | Useful for serviceable prototypes and assembly handoff | Generates a self-contained interactive BOM linked to board locations. Saves custom documentation work; it does not solve routing |
| [KiBot](https://github.com/INTI-CMNB/KiBot) | Evaluate when maintaining several projects or richer CI packages | Provides repeatable fabrication/documentation generation. The existing exporter can remain the baseline while configuration is migrated and checked |
| Additional general KiCad MCP servers / schematic generators | Evaluate only against a missing capability and a scratch-board test | The source session does not establish their reliability or token advantage. More tool definitions alone do not demonstrate better efficiency |

Freerouting's MCP guide provides both local Java operation and a public API bridge. For the local workflow, choose the documented local mode; the NPX quick start uses the public API and is a separate data-transfer decision. Pin the chosen package and test tool availability rather than assuming the installed 1.6.2 JAR contains modern MCP support.

## Read-only probe in this library

```powershell
python skills/kicad-preflight/scripts/probe_toolchain.py --cli 'C:/Program Files/KiCad/9.0/bin/kicad-cli.exe' --pcb-python 'C:/Program Files/KiCad/9.0/bin/python.exe' --java 'C:/Program Files/DIYLC/jre17/bin/java.exe' --router-jar 'C:/Users/fnk/Documents/KiCad/6.0/3rdparty/plugins/app_freerouting_kicad-plugin/jar/freerouting-1.6.2.jar' --out analysis/toolchain.json
```

Those paths are this machine's discovered baseline, not portable defaults. See [the actual probe result](../analysis/toolchain.json): KiCad reports 9.0.7, the required legacy functions are present, Java reports 17.0.14, and the old JAR exists. The CLI version probe also emits registry-permission diagnostics under the managed execution account despite returning 0; the probe retains them. It does not certify a full CAD operation or router compatibility, and no router job or system installation was performed here.

Before the next board, smoke-test export → route → import → refill → DRC on a disposable small project. Verify the saved rules, protected route preservation and reserved layer, then test the output package. Save the successful invocation and tool versions so each design starts with known capabilities.
