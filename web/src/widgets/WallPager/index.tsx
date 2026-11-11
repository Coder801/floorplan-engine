// Elevation pager: "[▦ Все стены] ‹ Кухня — стена 3 · 5 / 32 ›"; the wall name is a dropdown button listing
// all walls by room for quick jumps (Esc and a click outside close it); "▦" opens the "All walls"
// overview with thumbnails (WallGrid).

import { useEffect, useMemo, useRef } from "react";
import { wallRooms } from "@/engine/sheet/walls";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { usePopover } from "@/shared/popover";
import menu from "@/shared/styles/menu.module.scss";
import { Icon } from "@/ui/Icon";
import css from "./WallPager.module.scss";

interface Wall { key: string; title: string }

interface Props {
  walls: Wall[];
  at: number;
  onTurn: (step: number) => void;
  onPick: (index: number) => void;
  onAll?: () => void;  // the "All walls" overview
}

export function WallPager({ walls, at, onTurn, onPick, onAll }: Props) {
  const { open, closing, setOpen, toggle, ref } = usePopover<HTMLDivElement>();
  const { t } = useTranslation();
  const list = useRef<HTMLDivElement>(null);
  const rooms = useMemo(() => wallRooms(walls), [walls]);

  // On open, the current wall is scrolled into view
  useEffect(() => {
    if (open) list.current?.querySelector("[aria-selected='true']")?.scrollIntoView({ block: "center" });
  }, [open]);

  const wall = walls[at];
  return (
    <div ref={ref} className={css.at}>
      {onAll && (
        <button className={css.all} title={t("pager.overview")} onClick={onAll}>
          <Icon name="grid" /><span className={css.allLabel}>{t("pager.overview")}</span>
        </button>
      )}
      <div className={css.pager} role="group" aria-label={t("pager.walls")}>
        <button aria-label={t("pager.prev")} title="PageUp" disabled={at <= 0} onClick={() => onTurn(-1)}>‹</button>
        <button className={css.title} aria-haspopup="listbox" aria-expanded={open} title={t("pager.all")} onClick={toggle}>
          <span className={css.name}>{wall.title}</span>
          <span className="mono muted">{` · ${at + 1} / ${walls.length}`}</span>
          <span className={css.caret} aria-hidden="true">▾</span>
        </button>
        <button aria-label={t("pager.next")} title="PageDown" disabled={at >= walls.length - 1}
                onClick={() => onTurn(1)}>›</button>
      </div>
      {open && (
        <div ref={list} className={cx(menu.panel, css.list)} data-pop="" data-closing={closing || undefined} role="listbox" aria-label={t("pager.list")}>
          {rooms.map((r, k) => (
            <div key={k} className={css.room} role="group" aria-label={r.room || undefined}>
              {r.room && <div className={css.roomName}>{r.room}</div>}
              {r.items.map(({ index, wall: name }) => (
                <button key={index} className={menu.item} role="option" aria-selected={index === at}
                        onClick={() => { setOpen(false); if (index !== at) onPick(index); }}>
                  <span>{name}</span>
                  <span className={cx(menu.note, "mono")}>{index + 1}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
