// Экран приветствия: выбор проекта карточками на всю страницу, пока проект не открыт.
// Картинка карточки — превью плана из модели (out/preview.svg, пишет build); нет его —
// условный план, разбитый по имени проекта.

import { useEffect, useState } from "react";
import { base, getText } from "./api";
import { STAGE, STATUS } from "./consts";
import { cx } from "./cx";
import { Logo } from "./Logo";
import type { ProjectSummary } from "./types";
import css from "./Welcome.module.scss";

// Детерминированный генератор по имени: у проекта всегда одна и та же картинка
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

// Прямоугольник квартиры, разрезанный на комнаты по очереди вдоль длинной стороны
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
      {/* Проём в каждой комнате — разрыв в нижней или правой стене */}
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

// SVG пишет ядро (thumbnail.py): только пути и линии с классами, цвета — из Welcome.module.scss
function Preview({ p }: { p: ProjectSummary }) {
  const [svg, setSvg] = useState<string | null>(null);
  useEffect(() => {
    if (!p.preview) return;
    let alive = true;
    getText(`${base(p.name)}/out/preview.svg?t=${p.built ?? 0}`).then((t) => alive && setSvg(t), () => {});
    return () => { alive = false; };
  }, [p.name, p.preview, p.built]);
  if (!svg) return <Plan name={p.name} />;
  return <div className={cx(css.plan, css.real)} aria-hidden="true" dangerouslySetInnerHTML={{ __html: svg }} />;
}

const date = (t: number | null) =>
  (t ? new Date(t * 1000).toLocaleDateString("ru", { day: "numeric", month: "long", year: "numeric" }) : null);

// Карточка проекта: превью плана, этапы, когда собран; на входном экране и в меню проектов
export function ProjectCard({ p, onOpen, current = false }: {
  p: ProjectSummary;
  onOpen: (name: string) => void;
  current?: boolean;
}) {
  return (
    <button className={cx(css.card, current && css.current)} aria-current={current || undefined}
            onClick={() => onOpen(p.name)}>
      <Preview p={p} />
      <div className={css.body}>
        <div className={css.title}>{p.title}</div>
        <div className="mono muted">{p.name}</div>
        <div className={css.stages}>
          {p.stages.filter((s) => s.status !== "absent").map((s) => (
            <span key={s.stage} className={cx(css.chip, `st-${s.status}`)} title={STATUS[s.status] ?? s.status}>
              {STAGE[s.stage] ?? s.stage}
            </span>
          ))}
        </div>
        <div className={cx(css.meta, "small")}>
          <span className="muted">{date(p.built) ? `собран ${date(p.built)}` : "не собран"}</span>
          {p.open_questions > 0 && <span className="sev-major">вопросов: {p.open_questions}</span>}
          {p.stale && <span className="sev-critical">устарел</span>}
        </div>
      </div>
    </button>
  );
}

export function Welcome({ list, onOpen }: { list: ProjectSummary[]; onOpen: (name: string) => void }) {
  return (
    <div className={css.welcome} role="dialog" aria-modal="true" aria-labelledby="welcome-title">
      <div className={css.inner}>
        <div className={css.head}>
          <Logo size={56} />
          <div>
            <h1 id="welcome-title" className={css.brand}>Shtroba</h1>
            <p className="muted">знаем, что в стене</p>
          </div>
        </div>
        <p className={cx(css.lead, "muted")}>Выберите проект — листы, проводка и вопросы откроются в просмотре.</p>
        {!list.length && (
          <div className={css.none}>
            <div>Нет проектов в <span className="mono">projects/</span> — соберите хотя бы один:</div>
            <code className="mono">uv run floorplan-engine build projects/&lt;имя&gt;</code>
          </div>
        )}
        <div className={css.grid}>
          {list.map((p) => (
            <ProjectCard key={p.name} p={p} onOpen={onOpen} />
          ))}
        </div>
      </div>
    </div>
  );
}
