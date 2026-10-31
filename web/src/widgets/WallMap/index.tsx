// Мини-схема к развёртке (внизу слева чертежа): какая это стена — в квартире «в разрезе»,
// стена цветом, пол её помещения — подсветкой, перед стеной — человечек лицом к ней (с какой
// стороны смотрим). Статичная, из 3D-сцены (sheet/wallMap.ts)

import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { frame, viewer, wallMap } from "@/engine/sheet/wallMap";
import type { Scene, XY } from "@/shared/types";
import css from "./WallMap.module.scss";

// key — объект развёртки: elevation:bath.w3
export function WallMap({ scene, elevation, title, face }: { scene: Scene; elevation: string; title: string; face?: [XY, XY] }) {
  const { t } = useTranslation();
  const id = elevation.slice(elevation.indexOf(":") + 1);
  const room = id.split(".")[0];
  const faces = useMemo(() => wallMap(scene, `wall:${id}`, room, face), [scene, id, room, face]);
  const man = useMemo(() => (face ? viewer(scene, room, face) : null), [scene, room, face]);
  const [x0, y0, x1, y1] = frame(faces);
  const pad = Math.max(x1 - x0, y1 - y0) * 0.04;
  return (
    <figure className={css.map} aria-label={t("elevation.where", { title })}>
      <svg viewBox={`${x0 - pad} ${y0 - pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`} aria-hidden="true">
        {faces.map((f, i) => (
          <polygon key={i} className={css[f.kind]} points={f.pts.map(([x, y]) => `${x},${y}`).join(" ")} />
        ))}
        {man && <Pegman x={man.feet[0]} y={man.feet[1]} size={man.size} />}
      </svg>
      <figcaption>{title}</figcaption>
    </figure>
  );
}

// Человечек, как на картах: жёлтый, руки чуть в стороны; рисунок — в единицах роста 100,
// ноги — в (0, 0), над ними — тень
function Pegman({ x, y, size }: { x: number; y: number; size: number }) {
  return (
    <g className={css.pegman} transform={`translate(${x} ${y}) scale(${size / 100})`}>
      <ellipse className={css.shadow} cx="0" cy="0" rx="11" ry="3.5" />
      <path d="M -10,-64 C -10,-70 10,-70 10,-64 L 18,-45 C 19.5,-41.5 16,-39.5 14,-42 L 10,-51 L 10,-34 L 7,-2
               C 7,1 2,1 2,-2 L 0,-27 L -2,-2 C -2,1 -7,1 -7,-2 L -10,-34 L -10,-51 L -14,-42
               C -16,-39.5 -19.5,-41.5 -18,-45 Z" />
      <circle cx="0" cy="-81" r="10.5" />
    </g>
  );
}
