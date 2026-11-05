// "Panel" sheet: the panel front view in its own canvas (PanelView) from the panel data, zoom
// buttons and weak spots under the drawing, a device card on click (DeviceCard). The album PNG
// comes from "Download" (Viewer): the whole sheet from page primitives. The switch on top opens
// the stickers of the devices (StickersStage), a build without them has no switch.

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { PanelView } from "@/engine/panel/PanelView";
import { cx } from "@/shared/cx";
import ui from "@/shared/styles/ui.module.scss";
import type { Page, PanelData } from "@/shared/types";
import type { Zoom } from "@/shared/zoom";
import { ScaleBar } from "@/ui/ScaleBar";
import { ZoomRail } from "@/ui/ZoomRail";
import { DeviceCard } from "@/widgets/DeviceCard";
import type { StageHandle } from "@/widgets/SheetStage";
import { StickersStage } from "@/widgets/StickersStage";
import css from "./PanelStage.module.scss";

interface Props {
  page: Page;
  panel: PanelData;
  language?: string;  // project language (manifest), for labels missing in an old .epd
  stickersPdf?: string | null;  // out/panel-stickers.pdf of the build
}


export const PanelStage = forwardRef<StageHandle, Props>(function PanelStage({ page, panel, language, stickersPdf = null }, ref) {
  const { t } = useTranslation();
  const canvas = useRef<HTMLCanvasElement>(null);
  const pv = useRef<PanelView | null>(null);
  const [zoom, setZoom] = useState<Zoom>({ step: 0, label: "100%", pxPerMm: null });
  const [labels, setLabels] = useState(false);
  const showLabels = labels && !!panel.stickers;

  useEffect(() => {
    if (showLabels) return;
    const v = new PanelView(canvas.current!, canvas.current!.parentElement!, panel, language);
    v.onZoom = (z) => setZoom((p) => (p.step === z.step && p.pxPerMm === z.pxPerMm ? p : z));
    pv.current = v;
    return () => { v.destroy(); pv.current = null; };
  }, [panel, language, showLabels]);

  useImperativeHandle(ref, () => ({
    pending: () => 0,
  }), []);

  const major = panel.warnings.filter((w) => w.severity === "major").length;
  const tot = panel.totals;
  const kw = (w: number) => (w / 1000).toFixed(2).replace(".", ",");
  const mode = panel.stickers && (
    <div className={cx(ui.segmented, css.mode)} role="group" aria-label={t("panel.mode")}>
      <button className={cx(!showLabels && ui.on)} aria-pressed={!showLabels} onClick={() => setLabels(false)}>{t("panel.front")}</button>
      <button className={cx(showLabels && ui.on)} aria-pressed={showLabels} onClick={() => setLabels(true)}>{t("panel.stickers")}</button>
    </div>
  );
  if (showLabels) {
    return (
      <>
        <StickersStage stickers={panel.stickers!} pdf={stickersPdf} />
        {mode}
      </>
    );
  }
  return (
    <>
      {mode}
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
