// Карточка аппарата щита поверх чертежа: открывается кликом по строке таблицы или по
// аппарату (store.pinned = device:QF4). Назначение, строка таблицы аппаратов (аппарат,
// кабель, мощность, ток — с заголовками колонок), модель каталога, шина, потребители группы
// (из таблицы росписи) и слабые места. Закрыть — крестик, Esc или клик мимо аппаратов.

import { useEffect } from "react";
import { useView, view } from "../store";
import type { Page, PanelData } from "../types";

export function DeviceCard({ page, panel }: { page: Page; panel: PanelData }) {
  const pinned = useView((s) => s.pinned);
  const close = () => view.set({ pinned: null });

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => { if (ev.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const dev = pinned ? panel.devices.find((d) => d.key === pinned) : undefined;
  if (!dev) return null;
  const g = dev.group ? panel.groups[dev.group] : undefined;
  const [devices, consumers] = page.tables || [];
  const row = devices?.rows.find((r) => r.keys?.includes(dev.key));
  const loads = consumers?.rows.filter((r) => !r.section && r.keys?.includes(dev.key)) || [];
  const warnings = panel.warnings.filter((w) => w.group && w.group === dev.group);
  const m = dev.model;

  const fields: [string, string][] = [
    ["Назначение", g ? g.purpose + (g.purpose_assumed ? "*" : "") : dev.title],
  ];
  if (row && devices) {
    row.cells.forEach((c, i) => { if (i > 0 && c) fields.push([devices.columns[i], c]); });
  }
  fields.push(["Модель", `${m.brand === "generic" ? "типовая" : m.brand}${m.series ? ` ${m.series}` : ""} · ${m.modules} мод. · ${m.width}×${m.height} мм`]);
  fields.push(["Шина", dev.reserve ? "резервная" : "основная"]);
  if (g?.split_of) fields.push(["Линия", `часть ${g.split_of} — перегруз разделён на щите`]);

  return (
    <div className="device-card" role="dialog" aria-label={`Аппарат ${dev.id}`}>
      <div className="device-card-head">
        {g?.color && <span className="dot" style={{ background: g.color }} aria-hidden="true" />}
        <b>{dev.id}</b>
        <span className="muted">{dev.title}</span>
        <button aria-label="Закрыть" onClick={close}>×</button>
      </div>
      <dl>{fields.map(([k, v], i) => [<dt key={`t${i}`}>{k}</dt>, <dd key={`d${i}`}>{v}</dd>])}</dl>
      {loads.length > 0 && (
        <>
          <h4>Потребители · {loads.length}</h4>
          <ul className="loads">
            {loads.map((r, i) => (
              <li key={i}><span>{r.cells[1]}</span><span className="muted">{r.cells[2]}</span>
                <span className="mono">{r.cells[3]} Вт</span></li>
            ))}
          </ul>
        </>
      )}
      {warnings.length > 0 && (
        <>
          <h4>Слабые места</h4>
          <ul className="warns">{warnings.map((w, i) => <li key={i}>{w.text}</li>)}</ul>
        </>
      )}
    </div>
  );
}
