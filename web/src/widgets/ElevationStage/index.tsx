// Развёртка стены: свой canvas (ElevationView) из данных развёртки, кнопки масштаба;
// «Изометрия» — стена под 45° с частью соседней в углу (выбор запоминается в браузере).
// Не общий чертёж листов с планом: ни слоёв, ни подсветки стен и помещений, ни 3D.
// PNG для альбома — «Скачать» (Viewer), весь печатный лист из примитивов страницы.

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ElevationView, type ElevMode } from "@/engine/elevation/ElevationView";
import { remember, remembered } from "@/shared/palette";
import ui from "@/shared/styles/ui.module.scss";
import type { Elevation } from "@/shared/types";
import type { Zoom } from "@/shared/zoom";
import { ScaleBar } from "@/ui/ScaleBar";
import { ZoomRail } from "@/ui/ZoomRail";
import type { StageHandle } from "@/widgets/SheetStage";

interface Props {
  elevation: Elevation;
  withMap: boolean;  // внизу слева — мини-схема (WallMap): развёртка её обходит
}


export const ElevationStage = forwardRef<StageHandle, Props>(function ElevationStage({ elevation, withMap }, ref) {
  const { t } = useTranslation();
  const canvas = useRef<HTMLCanvasElement>(null);
  const ev = useRef<ElevationView | null>(null);
  const [zoom, setZoom] = useState<Zoom>({ step: 0, label: "100%", pxPerMm: null });
  const [mode, setMode] = useState<ElevMode>(() => (remembered("elevMode") === "iso" ? "iso" : "flat"));
  const first = useRef({ elevation, withMap, mode });
  first.current = { elevation, withMap, mode };

  useEffect(() => {
    const v = new ElevationView(canvas.current!, canvas.current!.parentElement!,
                                first.current.elevation, first.current.withMap, first.current.mode);
    v.onZoom = (z) => setZoom((p) => (p.step === z.step && p.pxPerMm === z.pxPerMm ? p : z));
    ev.current = v;
    return () => { v.destroy(); ev.current = null; };
  }, []);

  // Другая стена или вид — тот же холст, вся стена
  useEffect(() => { ev.current?.setData(elevation, withMap, mode); }, [elevation, withMap, mode]);

  const toggleIso = () => {
    const next = mode === "iso" ? "flat" : "iso";
    setMode(next);
    remember("elevMode", next);
  };

  useImperativeHandle(ref, () => ({ pending: () => 0 }), []);

  return (
    <>
      <canvas ref={canvas} tabIndex={0} aria-label={t("elevation.canvas", { title: elevation.title })} />
      <ZoomRail zoom={zoom} onStep={(s) => ev.current?.zoomTo(s)} onFit={() => ev.current?.fit()} fitLabel={t("elevation.fit")} />
      <div className={ui.toolbar}>
        <div className={ui.group}>
          <button aria-pressed={mode === "iso"} title={t("elevation.isoTitle")} onClick={toggleIso}>{t("elevation.iso")}</button>
        </div>
        <span className={ui.hint}>
          {elevation.height_assumed ? t("elevation.ceiling", { h: elevation.height }) : ""}
          {mode === "iso" ? t("elevation.isoHint") : t("elevation.hint")}
        </span>
        {/* В изометрии мм на экране разные по осям — линейки нет */}
        {mode === "flat" && <ScaleBar zoom={zoom} />}
      </div>
    </>
  );
});
