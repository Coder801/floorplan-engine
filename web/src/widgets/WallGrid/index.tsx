// "All walls": the elevations tab as an overview — every wall as a thumbnail, by room, in sheet
// order; a card opens its wall, "Back to the wall" (or Esc) returns to the one that was open

import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { wallRooms, type WallPage } from "@/engine/sheet/walls";
import { useView } from "@/shared/store";
import type { Page } from "@/shared/types";
import { drawThumb, THUMB_H, THUMB_W } from "./thumb";
import css from "./WallGrid.module.scss";

interface Props {
  walls: WallPage[];
  pages: readonly { index: number; page: Page }[];  // elevation sheets the walls are on
  at: number;  // the wall that was open
  onPick: (index: number) => void;
  onClose: () => void;
}

export function WallGrid({ walls, pages, at, onPick, onClose }: Props) {
  const { t } = useTranslation();
  const root = useRef<HTMLDivElement>(null);
  const rooms = useMemo(() => wallRooms(walls), [walls]);
  const theme = useView((s) => s.themeTick);

  // Thumbnails: drawn on open and again when the theme changes
  useEffect(() => {
    const byIndex = new Map(pages.map((p) => [p.index, p.page]));
    const dpr = window.devicePixelRatio || 1;
    root.current?.querySelectorAll<HTMLCanvasElement>("canvas[data-wall]").forEach((c) => {
      const wall = walls[Number(c.dataset.wall)];
      const page = wall && byIndex.get(wall.sheet);
      if (wall && page) drawThumb(c, page, wall, dpr);
    });
  }, [walls, pages, theme]);

  // The open wall's card is in view and focused; Esc goes back to it
  useEffect(() => {
    const current = root.current?.querySelector<HTMLButtonElement>("[aria-current='true']");
    current?.scrollIntoView({ block: "center" });
    current?.focus({ preventScroll: true });
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div ref={root} className={css.grid} data-pop="" role="region" aria-label={t("pager.overview")}>
      <header className={css.head}>
        <h2>{t("pager.overview")}</h2>
        <span className="small muted">{t("wallGrid.count", { n: walls.length })}</span>
        <button className={css.back} onClick={onClose}>← {t("wallGrid.back")}</button>
      </header>
      {rooms.map((r, k) => (
        <section key={k} className={css.room} aria-label={r.room || undefined}>
          {r.room && <h3>{r.room}</h3>}
          <div className={css.cards}>
            {r.items.map(({ index, wall }) => (
              <button key={index} className={css.card} aria-current={index === at || undefined}
                      aria-label={t("wallGrid.open", { title: walls[index].title })}
                      onClick={() => (index === at ? onClose() : onPick(index))}>
                <canvas data-wall={index} style={{ aspectRatio: `${THUMB_W} / ${THUMB_H}` }} aria-hidden="true" />
                <span className={css.name}>{wall}</span>
                <span className="mono muted small">{index + 1}</span>
              </button>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}
