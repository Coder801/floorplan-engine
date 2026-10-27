// Экран приветствия: выбор проекта карточками на всю страницу, пока проект не открыт.
// Картинка карточки — условный план, разбитый по имени проекта (не геометрия модели).

import { STAGE, STATUS } from "./consts";
import { Logo } from "./Logo";
import type { ProjectSummary } from "./types";

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
    <svg className="welcome-plan" viewBox="0 0 200 120" aria-hidden="true">
      {rs.map(([x, y, w, h], i) => <rect key={i} x={x} y={y} width={w} height={h} className="room" />)}
      <rect x={10} y={10} width={180} height={100} className="outline" />
      {/* Проём в каждой комнате — разрыв в нижней или правой стене */}
      {rs.map(([x, y, w, h], i) => {
        const horiz = rnd() < 0.5 && w > 30;
        return horiz
          ? <line key={i} x1={x + w * 0.3} y1={y + h} x2={x + w * 0.3 + 12} y2={y + h} className="gap" />
          : <line key={i} x1={x + w} y1={y + h * 0.3} x2={x + w} y2={y + h * 0.3 + 12} className="gap" />;
      })}
      {rs.slice(0, 3).map(([x, y, w, h], i) => <circle key={i} cx={x + w / 2} cy={y + h / 2} r={2.2} className="pt" />)}
    </svg>
  );
}

const date = (t: number | null) =>
  (t ? new Date(t * 1000).toLocaleDateString("ru", { day: "numeric", month: "long", year: "numeric" }) : null);

export function Welcome({ list, onOpen }: { list: ProjectSummary[]; onOpen: (name: string) => void }) {
  return (
    <div className="welcome" role="dialog" aria-modal="true" aria-labelledby="welcome-title">
      <div className="welcome-inner">
        <div className="welcome-head">
          <Logo size={56} />
          <div>
            <h1 id="welcome-title" className="brand">Shtroba</h1>
            <p className="muted">знаем, что в стене</p>
          </div>
        </div>
        <p className="welcome-lead muted">Выберите проект — листы, проводка и вопросы откроются в просмотре.</p>
        {!list.length && (
          <div className="welcome-none">
            <div>Нет проектов в <span className="mono">projects/</span> — соберите хотя бы один:</div>
            <code className="mono">uv run floorplan-engine build projects/&lt;имя&gt;</code>
          </div>
        )}
        <div className="welcome-grid">
          {list.map((p) => (
            <button key={p.name} className="welcome-card" onClick={() => onOpen(p.name)}>
              <Plan name={p.name} />
              <div className="welcome-body">
                <div className="welcome-title">{p.title}</div>
                <div className="mono muted">{p.name}</div>
                <div className="welcome-stages">
                  {p.stages.filter((s) => s.status !== "absent").map((s) => (
                    <span key={s.stage} className={`chip st-${s.status}`} title={STATUS[s.status] ?? s.status}>
                      {STAGE[s.stage] ?? s.stage}
                    </span>
                  ))}
                </div>
                <div className="welcome-meta small">
                  <span className="muted">{date(p.built) ? `собран ${date(p.built)}` : "не собран"}</span>
                  {p.open_questions > 0 && <span className="sev-major">вопросов: {p.open_questions}</span>}
                  {p.stale && <span className="sev-critical">устарел</span>}
                </div>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
