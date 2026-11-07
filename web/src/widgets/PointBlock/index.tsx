// Elevation of one socket block in a pinned hint: the posts, how far from the wall start and from
// the floor. A scheme, not to scale: the distances are numbers, the wall itself is on its elevation

import { useTranslation } from "react-i18next";
import type { PointBlock as Block } from "@/shared/types";
import css from "./PointBlock.module.scss";

const CORNER = 8, FLOOR = 118, CY = 44, DIM_Y = 88;  // viewBox 300 × 128
const MAX_POST = 40, MAX_ROW = 204;                  // 6 posts still fit between the corner and the edge

export function PointBlock({ block }: { block: Block }) {
  const { t } = useTranslation();
  const post = Math.min(MAX_POST, MAX_ROW / block.posts);
  const cx = 160, left = cx - (post * block.posts) / 2, right = left + post * block.posts;
  const dim = right + 12;
  return (
    <svg className={css.block} viewBox="0 0 300 128" role="img"
         aria-label={t("tip.blockAria", { n: block.posts, x: block.x, y: block.y })}>
      <path className={css.wall} d={`M${CORNER} 4V${FLOOR}H292`} />
      <rect className={css.frame} x={left} y={CY - post / 2} width={right - left} height={post} rx={3} />
      {Array.from({ length: block.posts }, (_, k) => (
        <circle key={k} className={css.post} cx={left + post * (k + 0.5)} cy={CY} r={post * 0.34} />
      ))}
      <path className={css.dim} d={`M${CORNER} ${DIM_Y}H${cx}M${cx} ${CY + post / 2}V${DIM_Y + 4}`} />
      <path className={css.dim} d={`M${right} ${CY}H${dim + 4}M${dim} ${CY}V${FLOOR}`} />
      <text x={(CORNER + cx) / 2} y={DIM_Y - 5}>{t("tip.mm", { v: block.x })}</text>
      <text x={dim - 5} y={FLOOR - 8} textAnchor="end">{t("tip.mm", { v: block.y })}</text>
    </svg>
  );
}
