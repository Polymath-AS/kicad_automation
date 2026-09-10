---
name: ee-design
description: Guide electrical design from intent through component selection, schematic, PCB layout, routing, and verification. Use for new PCB designs or substantial redesigns before invoking KiCad execution skills.
---

# EE Design Workflow

This skill owns the design process. The `kicad-*` skills describe how to perform KiCad operations safely; this skill decides what should be designed and when to move to the next stage.

The goal is to turn the user's intent into a sensible working design without unnecessarily stopping for questions.

## General behavior

Start by understanding what the user is trying to build.

Prefer to:

1. infer obvious engineering requirements from the stated intent;
2. inspect existing project context;
3. research suitable approaches or components when needed;
4. make reasonable, explicit assumptions;
5. propose a concrete solution.

Ask the user only when a missing decision would materially change the architecture or when several plausible choices have substantially different consequences.

Do not ask for information that can reasonably be inferred, researched, selected by engineering judgment, or changed later.

For example, prefer:

> "I'll assume 3.3 V logic and choose parts accordingly."

over:

> "What logic voltage would you like?"

Record important assumptions so they can be revised later.

## Stage 1 — Understand intent and propose the design

Before editing KiCad, briefly determine:

- what the board is supposed to do;
- major inputs and outputs;
- important constraints already stated by the user;
- major functional blocks;
- anything genuinely unknown that prevents choosing an architecture.

Then propose a practical architecture.

Do not create a long requirements questionnaire.

If the intent is sufficiently clear, proceed.

## Stage 2 — Choose components

Choose suitable components before building the schematic.

For important ICs and unusual parts:

- choose an exact part;
- check the datasheet;
- verify that it fits the intended electrical role;
- identify important support circuitry and layout requirements;
- confirm or create an appropriate symbol and footprint.

Prefer proven reference circuits and manufacturer recommendations where applicable.

Do not choose components merely because a KiCad symbol exists.

Do not spend unnecessary effort selecting exact manufacturer part numbers for ordinary resistors, capacitors, and similar generic components unless their characteristics matter.

If several components are viable, select a sensible default rather than asking the user unless the trade-off is important to the product intent.

## Stage 3 — Build and review the schematic

Use `kicad-schematic`.

Construct the design in logical functional blocks.

After adding each meaningful block:

- inspect the resulting connections;
- compare it with the relevant datasheet/reference design;
- run ERC where useful;
- fix obvious problems before continuing.

Before moving to PCB layout, review the complete schematic for engineering correctness.

Look especially for:

- incorrect supply or logic voltages;
- missing required support components;
- incorrect pull-ups, enables, resets, or unused pins;
- power-path mistakes;
- connector or interface mistakes;
- anything contradicted by the selected component datasheets.

ERC passing does not by itself mean the circuit is correct.

If the schematic appears sound, proceed without requiring user approval unless an unresolved design choice materially affects the product.

## Stage 4 — Decide PCB intent, place, and route

Before placement, determine the physical intent of the board.

Identify things such as:

- mechanically fixed parts;
- components that should stay together;
- electrically critical groups;
- sensitive, high-current, high-speed, RF, or otherwise special nets;
- obvious keepouts or routing priorities.

Do not over-specify constraints that the design does not need.

Use this intent with `kicad-placement`.

Examples of useful placement intent:

- keep decoupling capacitors close to their IC;
- keep switching-power loops compact;
- keep a matching network close to its RF device;
- keep connectors at required board edges;
- keep related functional blocks together.

Review the placement before routing.

Then use `kicad-autoroute`.

Route electrically important nets according to their needs first, then route ordinary signals.

Do not treat all nets as equivalent merely because the router can connect them.

## Stage 5 — Review and verify

After routing, perform a short engineering review of the finished board.

Check whether the layout still reflects the intended electrical design.

Pay particular attention to the parts of the circuit whose behavior depends on layout.

Then use `kicad-drc` and authoritative ERC/DRC validation.

A clean DRC means the PCB satisfies the configured design rules. It does not prove that the circuit itself is electrically correct.

Resolve significant problems before using `kicad-release`.

## Iteration

Design work is allowed to move backward.

If a later discovery shows that a component, schematic decision, placement, or routing choice is poor, revise it and continue from the affected stage.

Do not preserve an earlier decision merely because work has already been done downstream.

## Progress state

 For every new electrical project or substantial redesign, maintain `design/ee-state.yaml` using the repository template.

- current stage;
- important design intent;
- assumptions;
- important selected components;
- unresolved issues;
- key placement/routing intent.

Do not use the state file as a large requirements database.

## Core rule

Optimize for making good engineering progress.

Do not pester the user for information that competent engineering judgment can reasonably supply.

Stop and ask only when the missing answer is genuinely important enough that guessing would risk producing the wrong product.