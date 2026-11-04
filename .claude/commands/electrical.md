---
description: Electrical for a project → electrical.yaml, then build and a check of the electrical sheet
argument-hint: <project> <description of points, groups, panel, routes>
allowed-tools: Read, Write, Edit, Glob, Bash(uv run floorplan-engine:*), Bash(ls:*)
---

Add electrical to a project. Arguments: $ARGUMENTS
The first word is the project name (`projects/<name>/`); the rest describes the electrical work.

Read `src/floorplan_engine/service/analysis/analyzer_prompt.md` first: the translation rules live
there; the work order is in CLAUDE.md.

## 1. Context
- Read `projects/<name>/room.yaml`. If the file is missing or `check` fails on the plan, stop and
  say so.
- Read the existing `electrical.yaml` if there is one: new points are **appended**; do not delete
  or change points already there unless asked to.
- For orientation, open the plan sheet `out/artifact/01-plan.png` if it exists (`render-artifact`).
  Wall `id`s are in `room.yaml` (`walls[].id`).

## 2. Turning the description into points
- Every point has an `id` (`<room>_<type>_<n>`). Attach it to a wall: `room`, `wall` (the wall `id`
  from room.yaml, for example `w3`), `offset` to the **centre** of the symbol along the walk
  direction, and `height`. A ceiling light uses `ceiling: [x, y]` from the room `origin`.
- Turn a description like "200 mm to the right of the door" into an offset using the door's
  `offset` and `width` from room.yaml. Show the arithmetic.
- A count in a block is `count`, the group is `group` (QF1…), a note is `note`.
- The panel is `board`; routes are `cables` with an `id` (`cable_<n>`): `from: board`, `to` is a
  point `id`, `cable` is the cable size, `route` is wall / ceiling / floor.
- Do not invent what the description does not say (height, group, cable size): ask. Use typical
  heights (300 / 900 / 1700) only if the user agreed, and mark them as an assumption with a
  question in `intake.yaml` (`stage: electrical`, `target: points.<id>.height`, `assumption`).

## 3. Show and stop
Show a table **"id/No. → room → wall → offset → type → height → count → group → source"**, a table
of routes, and a list of assumptions and questions. Wait for confirmation.

## 4. After confirmation
1. Write `electrical.yaml`. Run `uv run floorplan-engine check projects/<name>`.
   If there is an error, show it and ask; do not adjust numbers to fit.
2. Run `uv run floorplan-engine build projects/<name>`.
3. Run `uv run floorplan-engine render-artifact projects/<name>` and open with Read the electrical
   sheet `out/artifact/02-electrical.png` (and the wiring sheet `03-wiring.png`). Check that:
   - every point is on the right wall and not inside a door or window opening;
   - symbols face into the room;
   - routes connect the right points;
   - group and height labels are readable;
   - the legend matches what is on the sheet.
4. Result: `out/project.dxf` (sheet "02 Електрика"), the number of points per group, assumptions.
