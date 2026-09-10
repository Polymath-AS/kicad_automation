---
name: kicad-autoroute
description: Generate, review, and safely promote KiCadRoutingTools placement and copper candidates with source isolation and ERC/DRC evidence.
---

Use the pinned KiCadRoutingTools service for bounded placement refinement and board routing. Read
`../../docs/KICAD_ROUTING_TOOLS.md` when defining operation-specific controls or running the full
integration workflow.

Inspect and save the live source first, then run `tools/kicad-routing.ps1 doctor`. Candidate plans
may contain conservative `placement` followed by `planes`, `diff`, and `route`. Use exact net names
for differential/plane controls, lock mechanical/RF-critical placement, and reject path escapes,
unknown options, relaxed fabrication policy, or source lock files. Never edit the source project;
the routing container must operate on staged copies through its read-only source mount.

Accept a candidate only from its independent original-rule ERC/DRC comparison and source hashes,
not from router exit status alone. `needs_review` is not clean, and passing DRC does not establish
impedance, thermal, or manufacturing signoff.

For promotion, use `scripts/kicad_live_promotion.py` for supported additive track deltas and
`scripts/kicad_live_placement.py` for footprint positions. Require stale-source rejection,
save/reopen/readback verification, net/geometry preservation, post-promotion validation, and
truthful rollback fields. The pinned live API cannot safely restore every saved copper delta:
preflight unsupported vias/removals and fail closed when rollback cannot be verified.
