// Мини-схема к развёртке (внизу слева чертежа): какая это стена — в квартире «в разрезе»,
// стена цветом, пол её помещения — подсветкой. Статичная, из 3D-сцены (sheet/wallMap.ts)

import { useMemo } from "react";
import { frame, wallMap } from "./sheet/wallMap";
import type { Scene } from "./types";
import css from "./WallMap.module.scss";

// key — объект развёртки: elevation:bath.w3
export function WallMap({ scene, elevation, title }: { scene: Scene; elevation: string; title: string }) {
  const id = elevation.slice(elevation.indexOf(":") + 1);
  const faces = useMemo(() => wallMap(scene, `wall:${id}`, id.split(".")[0]), [scene, id]);
  const [x0, y0, x1, y1] = frame(faces);
  const pad = Math.max(x1 - x0, y1 - y0) * 0.04;
  return (
    <figure className={css.map} aria-label={`Где стена: ${title}`}>
      <svg viewBox={`${x0 - pad} ${y0 - pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`} aria-hidden="true">
        {faces.map((f, i) => (
          <polygon key={i} className={css[f.kind]} points={f.pts.map(([x, y]) => `${x},${y}`).join(" ")} />
        ))}
      </svg>
      <figcaption>{title}</figcaption>
    </figure>
  );
}
