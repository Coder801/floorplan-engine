// Боковая панель развёртки — «На стене»: точки по номерам листа электрики (вид, отступ,
// высота, группа и откуда линия проводки), коробки и щит. Строка ↔ объект развёртки
// (store.hover / lit / pinned); «На проводке» — открыть лист проводки с этой линией.

import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { useView, view } from "@/shared/store";
import type { Elevation } from "@/shared/types";
import css from "./WallItems.module.scss";

interface Row {
  key: string;
  mark: string;          // номер точки или «К3», «ЩР»
  color: string | null;  // плашка номера — цвет группы
  name: string;
  where: string;         // отступ × высота, мм
  line: string | null;   // «QF4 · от К3»
  box?: boolean;
}

const mm = (x: number, y: number) => `${Math.round(x)} × ${Math.round(y)}`;
const line = (group: string | null, from: string | null, fromText: (f: string) => string) =>
  [group, from && fromText(from)].filter(Boolean).join(" · ") || null;

export function WallItems({ wall, onWiring }: { wall: Elevation; onWiring?: (key: string) => void }) {
  const { t } = useTranslation();
  const { hover, lit, pinned } = useView((s) => s);
  const rows = useMemo<Row[]>(() => {
    const via = (f: string) => t("wall.from", { from: f });
    return [
      ...wall.points.map((p) => ({
        key: p.key, mark: String(p.n), color: p.color, name: p.name, where: mm(p.x, p.y),
        line: line(p.group, p.from, via),
      })),
      ...wall.boxes.map((b) => ({
        key: b.key, mark: b.label, color: null, name: t("wall.box"), where: mm(b.x, b.y),
        line: line(b.group, b.from, via), box: true,
      })),
      ...(wall.board ? [{ key: wall.board.key, mark: wall.board.name, color: null, name: t("wall.board"),
                          where: mm(wall.board.x, wall.board.y), line: null }] : []),
    ];
  }, [wall, t]);
  const on = (k: string) => k === hover || k === pinned || !!lit?.has(k);

  // Объект под курсором или закреплённый — прокрутить к его строке
  useEffect(() => {
    document.querySelector(`.${css.list} .${css.lit}`)?.scrollIntoView({ block: "nearest" });
  }, [hover, pinned]);

  return (
    <div className={css.wall}>
      <p className="small muted">
        {t("wall.summary", {
          behind: wall.behind, length: Math.round(wall.length),
          height: `${Math.round(wall.height)}${wall.height_assumed ? "*" : ""}`,
        })}
      </p>
      {rows.length === 0 ? <div className="muted">{t("wall.onlyChases")}</div> : (
        <ul className={css.list}>
          <li className={css.head} aria-hidden="true"><span>{t("wall.no")}</span><span>{t("wall.what")}</span><span>{t("wall.where")}</span></li>
          {rows.map((r) => (
            <li key={r.key} className={cx(on(r.key) && css.lit)}
                onPointerEnter={() => view.set({ lit: new Set([r.key]) })}
                onPointerLeave={() => view.set({ lit: null })}
                onClick={() => view.set({ pinned: pinned === r.key ? null : r.key })}>
              <span className={cx(css.mark, r.box && css.box, !r.color && !r.box && css.plain)}
                    style={r.color ? { background: r.color } : undefined}>{r.mark}</span>
              <span className={css.name}>
                {r.name}
                {r.line && <span className={css.line}>{r.line}</span>}
              </span>
              <span className={cx(css.where, "mono")}>{r.where}</span>
              {onWiring && r.line && (
                <button className={css.go} title={t("wall.goTitle")}
                        onClick={(e) => { e.stopPropagation(); onWiring(r.key); }}>{t("wall.go")}</button>
              )}
            </li>
          ))}
        </ul>
      )}
      <p className="small muted">{t("wall.note")}</p>
    </div>
  );
}
