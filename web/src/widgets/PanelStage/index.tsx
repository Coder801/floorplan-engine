// "Panel" sheet: the panel front view in its own canvas (PanelView) from the panel data, zoom
// buttons and weak spots under the drawing, a device card on click (DeviceCard). The album PNG
// comes from "Download" (Viewer): the whole sheet from page primitives. The switch on top opens
// the stickers of the devices (StickersStage) and, with a backup, the groups kept on it
// (ReserveStage); a mode the build has no data for has no button, and without any there is no switch.

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { PanelView } from "@/engine/panel/PanelView";
import type { PanelMode } from "@/shared/consts";
import { cx } from "@/shared/cx";
import ui from "@/shared/styles/ui.module.scss";
import type { OverviewReserve, Page, PanelData } from "@/shared/types";
import type { Zoom } from "@/shared/zoom";
import { ScaleBar } from "@/ui/ScaleBar";
import { ZoomRail } from "@/ui/ZoomRail";
import { DeviceCard } from "@/widgets/DeviceCard";
import { ReserveStage } from "@/widgets/ReserveStage";
import type { StageHandle } from "@/widgets/SheetStage";
import { StickersStage, type StickerFile } from "@/widgets/StickersStage";
import { freshStickers } from "@/widgets/StickersStage/fresh";
import css from "./PanelStage.module.scss";

interface Props {
  page: Page;
  panel: PanelData;
  language?: string;  // project language (manifest), for labels missing in an old .epd
  stickersPdf?: StickerFile;
  mode: PanelMode;
  onMode: (m: PanelMode) => void;
  reserve?: OverviewReserve;
  reserveEditable: boolean;
  busy: boolean;
  onReserve: (groups: string[]) => Promise<void>;
}

const NO_FILE: StickerFile = () => null;

export const PanelStage = forwardRef<StageHandle, Props>(function PanelStage({ page, panel, language, stickersPdf = NO_FILE, mode, onMode, reserve, reserveEditable, busy, onReserve }, ref) {
  const { t } = useTranslation();
  const canvas = useRef<HTMLCanvasElement>(null);
  const pv = useRef<PanelView | null>(null);
  const [zoom, setZoom] = useState<Zoom>({ step: 0, label: "100%", pxPerMm: null });
  const stickers = freshStickers(panel.stickers);
  const showLabels = mode === "stickers" && !!stickers;
  const showReserve = mode === "reserve" && !!reserve;
  const front = !showLabels && !showReserve;

  useEffect(() => {
    if (!front) return;
    const v = new PanelView(canvas.current!, canvas.current!.parentElement!, panel, language);
    v.onZoom = (z) => setZoom((p) => (p.step === z.step && p.pxPerMm === z.pxPerMm ? p : z));
    pv.current = v;
    return () => { v.destroy(); pv.current = null; };
  }, [panel, language, front]);

  useImperativeHandle(ref, () => ({
    pending: () => 0,
  }), []);

  const major = panel.warnings.filter((w) => w.severity === "major").length;
  const tot = panel.totals;
  const kw = (w: number) => (w / 1000).toFixed(2).replace(".", ",");
  const modes = (stickers || reserve) && (
    <div className={cx(ui.segmented, css.mode)} role="group" aria-label={t("panel.mode")}>
      <button className={cx(front && ui.on)} aria-pressed={front} onClick={() => onMode("front")}>{t("panel.front")}</button>
      {stickers && <button className={cx(showLabels && ui.on)} aria-pressed={showLabels} onClick={() => onMode("stickers")}>{t("panel.stickers")}</button>}
      {reserve && <button className={cx(showReserve && ui.on)} aria-pressed={showReserve} onClick={() => onMode("reserve")}>{t("panel.reserve")}</button>}
    </div>
  );
  if (showLabels) {
    return (
      <>
        <StickersStage stickers={stickers!} file={stickersPdf} />
        {modes}
      </>
    );
  }
  if (showReserve) {
    return (
      <>
        <ReserveStage reserve={reserve!} editable={reserveEditable} busy={busy} onSave={onReserve} />
        {modes}
      </>
    );
  }
  return (
    <>
      {modes}
      <canvas ref={canvas} tabIndex={0} aria-label={t("panel.canvas")} />
      <DeviceCard page={page} panel={panel} />
      <ZoomRail zoom={zoom} onStep={(s) => pv.current?.zoomTo(s)} onFit={() => pv.current?.fit()} fitLabel={t("panel.fit")} />
      <div className={ui.toolbar}>
        <span className={ui.hint}>
          {t("panel.totals", {
            installed: kw(tot.installed), calculated: kw(tot.calculated), current: tot.current,
            input: `${panel.input.label}${panel.input.assumed ? "*" : ""}`,
          })}
          {major > 0 && ` · ${t("panel.weak", { n: major })}`}
          {` · ${t("panel.hint")}`}
        </span>
        <ScaleBar zoom={zoom} />
      </div>
    </>
  );
});
