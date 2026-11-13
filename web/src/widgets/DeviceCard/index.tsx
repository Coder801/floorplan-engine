// Panel device card over the drawing: opens on a click on a table row or a device
// (store.pinned = device:QF4). Purpose, the device table row (device, cable, power, current,
// with column headings), catalogue model, bus, group loads (from the load list) and weak spots.
// Close with the cross, Esc or a click off the devices.

import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { useView, view } from "@/shared/store";
import { Dot } from "@/ui/Dot";
import { Heading } from "@/ui/Heading";
import { IconButton } from "@/ui/IconButton";
import type { Page, PanelData } from "@/shared/types";
import css from "./DeviceCard.module.scss";

export function DeviceCard({ page, panel }: { page: Page; panel: PanelData }) {
  const { t } = useTranslation();
  const pinned = useView((s) => s.pinned);
  const close = () => view.set({ pinned: null });

  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => { if (ev.key === "Escape") close(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const all = [...panel.devices, ...(panel.dc?.devices || []), ...(panel.led?.devices || [])];
  const dev = pinned ? all.find((d) => d.key === pinned) : undefined;
  if (!dev) return null;
  const g = dev.group ? panel.groups[dev.group] : undefined;
  const [devices, consumers] = page.tables || [];
  const row = devices?.rows.find((r) => r.keys?.includes(dev.key));
  const loads = consumers?.rows.filter((r) => !r.section && r.keys?.includes(dev.key)) || [];
  const warnings = panel.warnings.filter((w) => w.group && w.group === dev.group);
  const m = dev.model;

  const fields: [string, string][] = [
    [t("device.purpose"), g ? g.purpose + (g.purpose_assumed ? "*" : "") : dev.title],
  ];
  if (row && devices) {
    row.cells.forEach((c, i) => { if (i > 0 && c) fields.push([devices.columns[i], c]); });
  }
  const brand = m.brand === "generic" ? t("device.typical") : m.brand;
  fields.push([t("device.model"), `${brand}${m.series ? ` ${m.series}` : ""} · ${t("device.modules", { n: m.modules })} · ${m.width}×${m.height} ${t("units.mm")}`]);
  fields.push([t("device.bus"), dev.reserve ? t("device.reserve") : t("device.main")]);
  if (g?.split_of) fields.push([t("device.line"), t("device.split", { group: g.split_of })]);

  return (
    <div className={css.card} role="dialog" aria-label={t("device.aria", { id: dev.id })}>
      <div className={css.head}>
        {g?.color && <Dot color={g.color} />}
        <b>{dev.id}</b>
        <span className={cx(css.title, "muted")}>{dev.title}</span>
        <IconButton variant="close" size="sm" className={css.close} label={t("common.close")} onClick={close} />
      </div>
      <dl>{fields.map(([k, v], i) => [<dt key={`t${i}`}>{k}</dt>, <dd key={`d${i}`}>{v}</dd>])}</dl>
      {loads.length > 0 && (
        <>
          <Heading level={4} size="subheading">{t("device.consumers", { n: loads.length })}</Heading>
          <ul className={css.loads}>
            {loads.map((r, i) => (
              <li key={i}><span>{r.cells[1]}</span><span className="muted">{r.cells[2]}</span>
                <span className="mono">{r.cells[3]} {t("units.w")}</span></li>
            ))}
          </ul>
        </>
      )}
      {warnings.length > 0 && (
        <>
          <Heading level={4} size="subheading">{t("device.weak")}</Heading>
          <ul className={css.warns}>{warnings.map((w, i) => <li key={i}>{w.text}</li>)}</ul>
        </>
      )}
    </div>
  );
}
