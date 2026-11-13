// Elevation of one frame in a pinned hint: every post in it (sockets, switches, internet, TV), how
// far from the wall start and from the floor. The posts of the point the hint is about stay bright,
// the rest of the frame is dimmed. A scheme, not to scale: the distances are numbers, the wall
// itself is on its elevation

import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import type { PointBlock as Block } from "@/shared/types";
import { framePosts } from "./posts";
import css from "./PointBlock.module.scss";

const CORNER = 8, FLOOR = 118, CY = 44, DIM_Y = 88;  // viewBox 300 × 128
const MAX_POST = 40, MAX_ROW = 204;                  // 6 posts still fit between the corner and the edge

// What stands in a post: a socket is a circle, a switch a key, internet and TV a plate with letters
function Glyph({ type, x, size }: { type: string; x: number; size: number }) {
  const r = size * 0.34;
  if (type === "switch" || type === "pass_switch") {
    // A plate with its key inside; a pass switch has the key split in two
    const k = r * 0.62;
    return (
      <>
        <rect className={css.post} x={x - r} y={CY - r} width={2 * r} height={2 * r} rx={2} />
        <rect className={css.post} x={x - k} y={CY - k} width={2 * k} height={2 * k} rx={1} />
        {type === "pass_switch" && <path className={css.post} d={`M${x} ${CY - k}V${CY + k}`} />}
      </>
    );
  }
  if (type === "data" || type === "tv") {
    return (
      <>
        <rect className={css.post} x={x - r} y={CY - r} width={2 * r} height={2 * r} rx={2} />
        <text className={css.mark} x={x} y={CY + 3} style={{ fontSize: Math.max(7, r * 0.75) }}>
          {type === "tv" ? "TV" : "INT"}
        </text>
      </>
    );
  }
  return <circle className={css.post} cx={x} cy={CY} r={r} />;
}

export function PointBlock({ block }: { block: Block }) {
  const { t } = useTranslation();
  const posts = framePosts(block);
  const post = Math.min(MAX_POST, MAX_ROW / posts.length);
  const cx0 = 160, left = cx0 - (post * posts.length) / 2, right = left + post * posts.length;
  const dim = right + 12;
  return (
    <svg className={css.block} viewBox="0 0 300 128" role="img"
         aria-label={t("tip.blockAria", { n: posts.length, x: block.x, y: block.y })}>
      <path className={css.wall} d={`M${CORNER} 4V${FLOOR}H292`} />
      <rect className={css.frame} x={left} y={CY - post / 2} width={right - left} height={post} rx={3} />
      {posts.map((p, k) => (
        <g key={k} className={cx(!p.own && css.other)}>
          <Glyph type={p.type} x={left + post * (k + 0.5)} size={post} />
        </g>
      ))}
      <path className={css.dim} d={`M${CORNER} ${DIM_Y}H${cx0}M${cx0} ${CY + post / 2}V${DIM_Y + 4}`} />
      <path className={css.dim} d={`M${right} ${CY}H${dim + 4}M${dim} ${CY}V${FLOOR}`} />
      <text x={(CORNER + cx0) / 2} y={DIM_Y - 5}>{t("tip.mm", { v: block.x })}</text>
      <text x={dim - 5} y={FLOOR - 8} textAnchor="end">{t("tip.mm", { v: block.y })}</text>
    </svg>
  );
}
