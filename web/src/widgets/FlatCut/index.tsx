// The client's own flat for the ceiling height step of the setup wizard: a cut-away isometry from
// the 3D scene (walls cut low to see the rooms, sheet/wallMap.ts), the ceiling as a dashed outline
// at the entered height and a dimension line with the number. Floors in one colour and walls in
// one light colour, a background; what the step is about in the highlight colour

import { useMemo } from "react";
import { ceilingGuide, CUT_SHARE, frame, wallMap } from "@/engine/sheet/wallMap";
import { cx } from "@/shared/cx";
import type { Scene, XY } from "@/shared/types";
import css from "./FlatCut.module.scss";

const pts = (list: readonly XY[]) => list.map(([x, y]) => `${x},${y}`).join(" ");

export function FlatCut({ scene, height }: { scene: Scene; height: number }) {
  const faces = useMemo(() => wallMap(scene, null, null, undefined, height * CUT_SHARE), [scene, height]);
  const guide = useMemo(() => ceilingGuide(scene, height), [scene, height]);
  // The frame holds the highest ceiling the step allows, so the picture does not jump while typing
  const [x0, y0, x1, y1] = useMemo(() => {
    const top = ceilingGuide(scene, 4000);
    return frame([...faces, ...(top ? [{ kind: "top" as const, pts: [...top.outline, top.dim.label] }] : [])]);
  }, [scene, faces]);
  const pad = Math.max(x1 - x0, y1 - y0) * 0.06;
  const font = (x1 - x0) * 0.065;
  return (
    <svg className={css.art} viewBox={`${x0 - pad - font * 2} ${y0 - pad} ${x1 - x0 + 2 * pad + font * 2} ${y1 - y0 + 2 * pad}`} aria-hidden="true">
      {faces.map((f, i) => <polygon key={i} className={cx(css[f.kind], f.room && css[f.room])} points={pts(f.pts)} />)}
      {guide && (
        <>
          {guide.posts.map(([a, b], i) => <polyline key={i} className={css.post} points={pts([a, b])} />)}
          <polygon className={css.ceiling} points={pts(guide.outline)} />
          <polyline className={css.dim} points={pts([guide.dim.from, guide.dim.to])} />
          {[guide.dim.from, guide.dim.to].map(([x, y], i) => (
            <polyline key={i} className={css.dim} points={pts([[x - font * 0.3, y], [x + font * 0.3, y]])} />
          ))}
          <text className={css.label} x={guide.dim.label[0]} y={guide.dim.label[1]} fontSize={font}
                textAnchor="end" dominantBaseline="middle">{Math.round(height)}</text>
        </>
      )}
    </svg>
  );
}
