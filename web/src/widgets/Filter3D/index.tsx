// Фильтр 3D проводки: группы QF (флажки с цветом группы) и помещение. Отфильтрованные линии,
// точки и коробки не рисуются; щит виден всегда. Сбрасывается сменой листа.

import { useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import type { PageIndex } from "@/shared/page";
import { screenColor } from "@/shared/palette";
import { useView, view } from "@/shared/store";
import ui from "@/shared/styles/ui.module.scss";
import type { Scene } from "@/shared/types";
import css from "./Filter3D.module.scss";

// QF2 < QF10, QF8 < QF8.2
const byNumber = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true });

export function Filter3D({ scene, index }: { scene: Scene; index: PageIndex }) {
  const filter = useView((s) => s.filter3d);
  const [open, setOpen] = useState(false);
  const groups = useMemo(() => {
    const color = new Map<string, string>();
    for (const w of Object.values(scene.wires)) if (!color.has(w.group)) color.set(w.group, w.color);
    return [...color].sort(([a], [b]) => byNumber(a, b));
  }, [scene]);
  const rooms = useMemo(() => scene.floors.map((f) => ({
    id: f.key.slice(f.key.indexOf(":") + 1), name: index.card(f.key).title,
  })), [scene, index]);

  const set = (patch: Partial<typeof filter>) =>
    view.set({ filter3d: { ...filter, ...patch }, selected: null, neighbors: null, pinned: null, tip: null });
  const toggle = (g: string) => {
    const on = new Set(filter.groups ?? groups.map(([k]) => k));
    if (on.has(g)) on.delete(g); else on.add(g);
    set({ groups: on.size === groups.length ? null : on });
  };
  const only = (g: string) => set({ groups: new Set([g]) });
  const n = filter.groups ? filter.groups.size : groups.length;
  const { t } = useTranslation();

  return (
    <div className={cx(ui.group, css.filter)}>
      <select aria-label={t("filter3d.room")} value={filter.room ?? ""}
              onChange={(e) => set({ room: e.target.value || null })}>
        <option value="">{t("filter3d.allRooms")}</option>
        {rooms.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
      </select>
      <button aria-expanded={open} aria-pressed={!!filter.groups} onClick={() => setOpen(!open)}
              title={t("filter3d.groupsTitle")}>
        {filter.groups ? t("filter3d.groupsN", { n, total: groups.length }) : t("filter3d.allGroups")}
      </button>
      {/* Всплывашка — в области чертежа, а не в группе кнопок: та обрезает всё, что за краем */}
      {open && createPortal(
        <div className={css.pop} role="dialog" aria-label={t("filter3d.groups")}>
          <div className={css.head}>
            <button onClick={() => set({ groups: null })}>{t("filter3d.all")}</button>
            <button onClick={() => set({ groups: new Set() })}>{t("filter3d.none")}</button>
          </div>
          {groups.map(([g, c]) => (
            <label key={g} className={css.row}>
              <input type="checkbox" checked={!filter.groups || filter.groups.has(g)} onChange={() => toggle(g)} />
              <span className={css.swatch} style={{ background: screenColor(c) }} />
              <span className="mono">{g}</span>
              <button className={css.only} title={t("filter3d.onlyGroup", { group: g })} onClick={(e) => { e.preventDefault(); only(g); }}>{t("filter3d.only")}</button>
            </label>
          ))}
        </div>,
        document.getElementById("stage")!,
      )}
    </div>
  );
}
