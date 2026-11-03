---
description: Validate a project and its preview without regenerating YAML or DXF
argument-hint: <project>
allowed-tools: Read, Glob, Bash(uv run floorplan-engine check:*), Bash(uv run floorplan-engine render-artifact:*), Bash(ls:*)
---

Check the project `projects/$ARGUMENTS/`. Only check; do not fix anything.

1. Run `uv run floorplan-engine check projects/$ARGUMENTS`. Retell the errors and warnings in
   Russian with the paths to the YAML fields. If the outline does not close, show ΔX/ΔY and the fix
   options from the message and ask which size is wrong. Do not edit the YAML.
   Retell the status of each stage (ready / has questions / not enough data / no data) and the open
   questions from `intake.yaml`, critical ones first.
2. If `out/project.epd` exists, run `uv run floorplan-engine render-artifact projects/$ARGUMENTS`,
   then open `out/artifact/*.png` with Read and check that:
   - the outline is closed;
   - the openings are in place;
   - the dimensions are readable;
   - the electrical items are on their walls;
   - labels do not overlap each other.
3. If the YAML is newer than the DXF (compare with `ls -l`), warn that the preview is stale and a
   `build` is needed. Do not run `build` yourself.
4. Result: either everything is fine, or a list of problems with the file and the field.
