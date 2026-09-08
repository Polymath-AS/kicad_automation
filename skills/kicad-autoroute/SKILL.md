---
name: kicad-autoroute
description: Route ordinary KiCad PCB connections through a verified Freerouting DSN/SES workflow while preserving critical copper and validating native design rules.
---

Use bulk routing once placement, saved rules, pad escapes, and critical paths are ready. Let the router solve ordinary connections; use targeted manual or scripted geometry for topology-sensitive nets and residual failures. Native KiCad DRC is the acceptance authority for geometric checks, alongside explicit electrical layout requirements.

Work on a candidate copy of the project. Verify project-loaded export, routed-copper protection, reserved layers, widths and clearances before starting. Read [the routing contract](references/routing-contract.md) when setting up export/import or changing router versions.

Prefer an existing bounded CLI job or a tested composite local routing tool that accepts file paths and returns an SES path plus compact statistics. If using MCP, establish whether it runs locally or uploads to a service. Do not send board geometry to a new service merely because a local plugin is installed.

Run with a documented time/pass budget and keep logs on disk. If progress stalls, inspect the failure once; adjust the identified cause or change strategy. Freerouting 1.6.2 in the source session stalled in multithreaded optimization and succeeded with `-mt 1`; this is a legacy workaround, not a universal setting for newer releases. Avoid repeated model turns that only poll an unchanged job.

Import only a successful, fresh SES tied to the current exported board. Rebuild connectivity, refill zones, and run native DRC plus schematic parity. Compare open items and violation fingerprints with the baseline; also confirm protected routes, net assignments, plane usage, and critical geometry survived.

Group residual failures by net and physical region. Repair common causes in a bounded batch, then reroute affected ordinary nets. If a candidate does not improve the objective without regression, retain the last accepted board and inspect placement/escapes/rules before another run. Do not loosen valid constraints merely to obtain a clean count.
