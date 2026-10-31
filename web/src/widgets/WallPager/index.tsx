// Пейджер развёрток: «‹ Кухня — стена 3 · 5 / 32 ›», имя стены — кнопка выпадающего списка
// всех стен по помещениям для быстрого перехода (Esc и клик мимо — закрыть).

import { useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { usePopover } from "@/shared/popover";
import menu from "@/shared/styles/menu.module.scss";
import css from "./WallPager.module.scss";

interface Wall { key: string; title: string }

interface Props {
  walls: Wall[];
  at: number;
  onTurn: (step: number) => void;
  onPick: (index: number) => void;
}

// «Санвузол 2 (пральня) — стіна 2» → помещение и стена; без « — » — всё имя стеной
const split = (title: string): [string, string] => {
  const k = title.lastIndexOf(" — ");
  return k < 0 ? ["", title] : [title.slice(0, k), title.slice(k + 3)];
};

export function WallPager({ walls, at, onTurn, onPick }: Props) {
  const { open, setOpen, toggle, ref } = usePopover<HTMLDivElement>();
  const { t } = useTranslation();
  const list = useRef<HTMLDivElement>(null);
  // Стены по помещениям в порядке листов
  const rooms = useMemo(() => {
    const out: { room: string; items: { index: number; wall: string }[] }[] = [];
    walls.forEach((w, index) => {
      const [room, wall] = split(w.title);
      const last = out[out.length - 1];
      if (last && last.room === room) last.items.push({ index, wall });
      else out.push({ room, items: [{ index, wall }] });
    });
    return out;
  }, [walls]);

  // Открыли — текущая стена в поле зрения
  useEffect(() => {
    if (open) list.current?.querySelector("[aria-selected='true']")?.scrollIntoView({ block: "center" });
  }, [open]);

  const wall = walls[at];
  return (
    <div ref={ref} className={css.at}>
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
        <div ref={list} className={cx(menu.panel, css.list)} role="listbox" aria-label={t("pager.list")}>
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
