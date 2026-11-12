// Elevation side panel, "On the wall", with two sections, each with its own visibility eye:
// "Electrical": points by electrical sheet number (kind, offset, height, group and where the
// wiring line comes from), boxes and the panel; "Water": water outlets and drains by the
// "Plumbing" sheet number. The eye hides the layer on the elevation (store.wallLayers), the
// rows stay, faint.
// Row ↔ elevation object (store.hover / lit / pinned); "On wiring" opens the wiring sheet at
// this line.

import { useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { WATER } from "@/engine/elevation/ElevationView";
import { cx } from "@/shared/cx";
import { useView, view, type WallLayers } from "@/shared/store";
import type { Elevation } from "@/shared/types";
import { Button } from "@/ui/Button";
import { EyeToggle } from "@/ui/EyeToggle";
import { Text } from "@/ui/Text";
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

  // Object under the cursor or pinned: scroll to its row
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
                <Button size="sm" className={css.go} title={t("wall.goTitle")}
                        onClick={(e) => { e.stopPropagation(); onWiring(r.key); }}>{t("wall.go")}</Button>
              )}
            </li>
          ))}
        </ul>
      </section>
    );
  };

  return (
    <div className={css.wall}>
      <Text size="small" tone="muted">
        {t("wall.summary", {
          behind: wall.behind, length: Math.round(wall.length),
          height: `${Math.round(wall.height)}${wall.height_assumed ? "*" : ""}`,
        })}
      </Text>
      {rows.electrical.length === 0 && rows.water.length === 0 ? <Text tone="muted">{t("wall.onlyChases")}</Text> : (
        <>
          {(rows.electrical.length > 0 || wall.chases.length > 0) && section("electrical", rows.electrical, true)}
          {rows.water.length > 0 && section("water", rows.water, false)}
        </>
      )}
      <Text size="small" tone="muted">{t("wall.note")}</Text>
    </div>
  );
}
