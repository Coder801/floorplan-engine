// Project card: plan preview, stages, build time, on the start screen (Welcome) and in the
// project menu (ProjectsMenu). The image is the plan preview from the model (out/preview.svg,
// written by build); without it, a placeholder plan derived from the project name.

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { base, getText } from "@/shared/api";
import { cx } from "@/shared/cx";
import { label, locale } from "@/shared/i18n";
import type { ProjectSummary } from "@/shared/types";
import { Card } from "@/ui/Card";
import { Tag } from "@/ui/Tag";
import { Text } from "@/ui/Text";
import css from "./ProjectCard.module.scss";

// Deterministic generator seeded by the name: a project always gets the same picture
function seeded(name: string) {
  let h = 2166136261;
  for (const ch of name) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
  return () => {
    h = Math.imul(h ^ (h >>> 15), 2246822507);
    h = Math.imul(h ^ (h >>> 13), 3266489909);
    return ((h ^= h >>> 16) >>> 0) / 4294967296;
  };
}

type Rect = [number, number, number, number];

// The flat rectangle, cut into rooms one by one along the long side
function rooms(name: string): Rect[] {
  const rnd = seeded(name);
  const out: Rect[] = [];
  const split = (r: Rect, depth: number) => {
    const [x, y, w, h] = r;
    if (depth === 0 || (w < 50 && h < 50)) { out.push(r); return; }
    const k = 0.35 + rnd() * 0.3;
    if (w >= h) {
      const a = Math.round(w * k);
      split([x, y, a, h], depth - 1); split([x + a, y, w - a, h], depth - 1 - (rnd() < 0.4 ? 1 : 0));
    } else {
      const a = Math.round(h * k);
      split([x, y, w, a], depth - 1 - (rnd() < 0.4 ? 1 : 0)); split([x, y + a, w, h - a], depth - 1);
    }
  };
  split([10, 10, 180, 100], 3);
  return out;
}

function Plan({ name }: { name: string }) {
  const rs = rooms(name);
  const rnd = seeded(`${name}/doors`);
  return (
    <svg className={css.plan} viewBox="0 0 200 120" aria-hidden="true">
      {rs.map(([x, y, w, h], i) => <rect key={i} x={x} y={y} width={w} height={h} className={css.room} />)}
      <rect x={10} y={10} width={180} height={100} className={css.outline} />
      {/* An opening in each room: a gap in the bottom or right wall */}
      {rs.map(([x, y, w, h], i) => {
        const horiz = rnd() < 0.5 && w > 30;
        return horiz
          ? <line key={i} x1={x + w * 0.3} y1={y + h} x2={x + w * 0.3 + 12} y2={y + h} className={css.gap} />
          : <line key={i} x1={x + w} y1={y + h * 0.3} x2={x + w} y2={y + h * 0.3 + 12} className={css.gap} />;
      })}
      {rs.slice(0, 3).map(([x, y, w, h], i) => <circle key={i} cx={x + w / 2} cy={y + h / 2} r={2.2} className={css.pt} />)}
    </svg>
  );
}

// The core writes the SVG (thumbnail.py): only paths and lines with classes, colours come from ProjectCard.module.scss
function Preview({ p }: { p: ProjectSummary }) {
  const [svg, setSvg] = useState<string | null>(null);
  useEffect(() => {
    if (!p.preview) return;
    let alive = true;
    getText(`${base(p.id)}/out/preview.svg?t=${p.built ?? 0}`).then((t) => alive && setSvg(t), () => {});
    return () => { alive = false; };
  }, [p.id, p.preview, p.built]);
  if (!svg) return <Plan name={p.name} />;
  return <div className={cx(css.plan, css.real)} aria-hidden="true" dangerouslySetInnerHTML={{ __html: svg }} />;
}

const date = (t: number | null) =>
  (t ? new Date(t * 1000).toLocaleDateString(locale(), { day: "numeric", month: "long", year: "numeric" }) : null);

export function ProjectCard({ p, onOpen, current = false }: {
  p: ProjectSummary;
  onOpen: (key: string) => void;
  current?: boolean;
}) {
  const { t } = useTranslation();
  const built = date(p.built);
  return (
    <Card as="button" type="button" variant="panel" padding="none" interactive selected={current} className={css.card}
          aria-current={current || undefined} onClick={() => onOpen(p.id)}>
      <Preview p={p} />
      <div className={css.body}>
        <Text as="div" weight="bold" className={css.title}>{p.title}</Text>
        <Text as="div" size="small" tone="muted" mono>{p.name}</Text>
        <div className={css.stages}>
          {p.stages.filter((s) => s.status !== "absent").map((s) => (
            <Tag key={s.stage} variant="outline" tone="inherit" className={`st-${s.status}`} title={label("status", s.status)}>
              {label("stage", s.stage)}
            </Tag>
          ))}
        </div>
        <div className={cx(css.meta, "small")}>
          <span className="muted">{built ? t("welcome.built", { date: built }) : t("welcome.notBuilt")}</span>
          {p.open_questions > 0 && <span className="sev-major">{t("welcome.questions", { n: p.open_questions })}</span>}
          {p.stale && <span className="sev-critical">{t("welcome.stale")}</span>}
        </div>
      </div>
    </Card>
  );
}
