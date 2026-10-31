// Лист «Щит»: щит в лицо в своём canvas (PanelView) из данных щита, кнопки масштаба
// и слабые места под чертежом, карточка аппарата по клику (DeviceCard). PNG для альбома —
// «Скачать» (Viewer), весь лист из примитивов страницы.

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { PanelView } from "@/engine/panel/PanelView";
import ui from "@/shared/styles/ui.module.scss";
import type { Page, PanelData } from "@/shared/types";
import type { Zoom } from "@/shared/zoom";
import { ScaleBar } from "@/ui/ScaleBar";
import { ZoomRail } from "@/ui/ZoomRail";
import { DeviceCard } from "@/widgets/DeviceCard";
import type { StageHandle } from "@/widgets/SheetStage";

interface Props {
  page: Page;
  panel: PanelData;
}


export const PanelStage = forwardRef<StageHandle, Props>(function PanelStage({ page, panel }, ref) {
  const { t } = useTranslation();
  const canvas = useRef<HTMLCanvasElement>(null);
  const pv = useRef<PanelView | null>(null);
  const [zoom, setZoom] = useState<Zoom>({ step: 0, label: "100%", pxPerMm: null });

  useEffect(() => {
    const v = new PanelView(canvas.current!, canvas.current!.parentElement!, panel);
    v.onZoom = (z) => setZoom((p) => (p.step === z.step && p.pxPerMm === z.pxPerMm ? p : z));
    pv.current = v;
    return () => { v.destroy(); pv.current = null; };
  }, [panel]);

  useImperativeHandle(ref, () => ({
    pending: () => 0,
  }), []);

  const major = panel.warnings.filter((w) => w.severity === "major").length;
  const tot = panel.totals;
  const kw = (w: number) => (w / 1000).toFixed(2).replace(".", ",");
  return (
    <>
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
