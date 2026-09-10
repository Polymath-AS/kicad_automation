# Connector/RF placement intent fixture

`placement_intent.json` is a deterministic repository-side constraint fixture. It models a
left-edge connector, an RF module whose antenna keepout is on the right edge, and a locked
connector. The planner tests use it to prove valid placement, antenna blocking, connector-edge
requirements, and locked-part atomic failure without mutating the source fixture.
