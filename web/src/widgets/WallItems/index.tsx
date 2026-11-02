// Боковая панель развёртки — «На стене», двумя разделами со своим глазом видимости:
// «Электрика» — точки по номерам листа электрики (вид, отступ, высота, группа и откуда линия
// проводки), коробки и щит; «Вода» — водорозетки и выпуски по номерам листа «Сантехника».
// Глаз скрывает слой на развёртке (store.wallLayers), строки остаются бледными.
// Строка ↔ объект развёртки (store.hover / lit / pinned); «На проводке» — открыть лист
// проводки с этой линией.

import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { WATER } from "@/engine/elevation/ElevationView";
import { cx } from "@/shared/cx";
import { useView, view, type WallLayers } from "@/shared/store";
import type { Elevation } from "@/shared/types";
import { EyeToggle } from "@/ui/EyeToggle";
import { type Row, wallRows } from "./rows";
import css from "./WallItems.module.scss";

export function WallItems({ wall, onWiring }: { wall: Elevation; onWiring?: (key: string) => void }) {
  const { t } = useTranslation();
  const { hover, lit, pinned, wallLayers } = useView((s) => s);
  const rows = useMemo(() => wallRows(wall, {
    from: (f) => t("wall.from", { from: f }), box: t("wall.box"), board: t("wall.board"),
    kind: { cold: t("wall.kind.cold"), hot: t("wall.kind.hot"), sewer: t("wall.kind.sewer") },
  }, WATER), [wall, t]);
  const on = (k: string) => k === hover || k === pinned || !!lit?.has(k);

  // Объект под курсором или закреплённый — прокрутить к его строке
  useEffect(() => {
    document.querySelector(`.${css.list} .${css.lit}`)?.scrollIntoView({ block: "nearest" });
  }, [hover, pinned]);

  const section = (layer: keyof WallLayers, list: Row[], wiring: boolean) => {
    const shown = wallLayers[layer];
    const title = t(`wall.${layer}`);
    return (
      <section className={cx(css.section, !shown && css.off)}>
        <h3 className={css.title}>
          <EyeToggle on={shown} what={title}
                     onToggle={() => view.set({ wallLayers: { ...wallLayers, [layer]: !shown } })} />
          {title}
          <span className={css.count}>{list.length}</span>
        </h3>
        <ul className={css.list}>
          <li className={css.head} aria-hidden="true"><span>{t("wall.no")}</span><span>{t("wall.what")}</span><span>{t("wall.where")}</span></li>
          {list.map((r) => (
            <li key={r.id} className={cx(on(r.key) && css.lit)}
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
              {wiring && onWiring && r.line && (
                <button className={css.go} title={t("wall.goTitle")}
                        onClick={(e) => { e.stopPropagation(); onWiring(r.key); }}>{t("wall.go")}</button>
              )}
            </li>
          ))}
        </ul>
      </section>
    );
  };

  return (
    <div className={css.wall}>
      <p className="small muted">
        {t("wall.summary", {
          behind: wall.behind, length: Math.round(wall.length),
          height: `${Math.round(wall.height)}${wall.height_assumed ? "*" : ""}`,
        })}
      </p>
      {rows.electrical.length === 0 && rows.water.length === 0 ? <div className="muted">{t("wall.onlyChases")}</div> : (
        <>
          {(rows.electrical.length > 0 || wall.chases.length > 0) && section("electrical", rows.electrical, true)}
          {rows.water.length > 0 && section("water", rows.water, false)}
        </>
      )}
      <p className="small muted">{t("wall.note")}</p>
    </div>
  );
}
