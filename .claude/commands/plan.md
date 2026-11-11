---
description: Room plan from a photo or text → projects/<name>/room.yaml, a size table, then check + build after confirmation
argument-hint: <path to photo | text description> [project name]
allowed-tools: Read, Write, Edit, Glob, Bash(uv run floorplan-engine:*), Bash(mkdir:*), Bash(cp:*), Bash(ls:*)
---

Create a room plan from the input: $ARGUMENTS

Read `src/floorplan_engine/service/analysis/analyzer_prompt.md` first: the translation rules live
there; the work order is in CLAUDE.md. Above all: only sizes from the photo or the text, no estimating by
eye and no adjusting to fit.

## 1. Input and project folder
- If the arguments contain a path to an existing image (jpg/png/heic/webp), it is a photo:
  `source: photo`.
- If the image is a hand drawing (a sketch, a plan on paper or drawn over a photo), do not parse it
  (rule 7 in `analyzer_prompt.md`): do not write `room.yaml`, only `intake.yaml` with the source marked
  `note: "рисунок от руки — не разбирается"` and a critical question "пришлите чертёж в PDF или
  обмерный план (DWG — в разработке: пока сохраните его в PDF)". A DWG or DXF source is not read
  yet (in development): list it and ask for a PDF of it (rule 7 in `analyzer_prompt.md`). Tell the user.
  Otherwise it is a text description: `source: text`. If the user says they measured it
  themselves: `source: measured`.
- Project name: from the arguments if given; otherwise make up a short Latin name and state it.
  If `projects/<name>/` already exists, ask whether to overwrite it and do not touch any files until
  you get an answer.
- Create `projects/<name>/source/` and `projects/<name>/out/`. Copy the photo into `source/`.
  Save a text description word for word in `source/notes.md`.

## 2. Recognition
- Open the photo with Read. Write down **only the numbers written on it**, and what each refers to.
- Build the walk: `origin` is the bottom-left inner corner, walls go clockwise along the inner
  outline, the first one goes up. For each corner set `turn`: 90, or 270 for a reflex corner.
- Openings: wall, type (door / window / opening), `offset` from the wall start along the walk,
  `width`, and `sill` for windows if it is written.
- Anything not visible or ambiguous becomes a question in `intake.yaml` (with `target`,
  `assumption`, `also` per `analyzer_prompt.md`), never an invented number. With no geometry at all, write only
  `intake.yaml`.
- Check the closure yourself: add up the wall projections on X and Y.

## 3. Show and stop
Write a draft `room.yaml` and show:
1. A table **"wall id → direction → length → thickness → source (photo / text / assumption)"**.
2. A table of openings: id, wall (id), type, offset, width, sill, source.
3. The closure check: Σ on X, Σ on Y.
4. Questions from `intake.yaml`: id, question, field, what the model holds now, weight
   (critical / major / minor).
5. Assumptions: default thickness, door swing, and so on.

**Do not go further.** Wait for confirmation or corrections. Apply corrections to `room.yaml` and
show the table again.

## 4. After confirmation
1. Run `uv run floorplan-engine check projects/<name>`.
   If there is an error, do not change numbers yourself: show the closure error and the suggested
   options and ask which size is wrong.
2. Run `uv run floorplan-engine build projects/<name>`.
3. Run `uv run floorplan-engine render-artifact projects/<name>`, open the plan sheet
   `projects/<name>/out/artifact/01-plan.png` with Read and check that:
   - the outline is closed and the walls are in place;
   - each opening is on its wall, on the right side, at the right width; the door arc opens the
     right way;
   - dimensions are readable and match the table;
   - labels do not overlap each other.
   If something is wrong, find the cause in the YAML, show it and ask before changing anything.
4. Result: file paths, room areas, stage status and open questions from `out/report.md`, and the
   assumptions as a list.
