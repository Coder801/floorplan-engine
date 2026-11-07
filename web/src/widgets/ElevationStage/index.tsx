// Wall elevation: its own canvas (ElevationView) from the elevation data, zoom buttons;
// "Isometry" shows the wall at 45° with part of the neighbouring one at the corner (the choice
// is remembered in the browser). Not the shared drawing of plan sheets: no sheet layers, no
// wall and room highlighting, no 3D; electrical and water are toggled with the eye in "On the
// wall" (store.wallLayers).
// The album PNG comes from "Download" (Viewer): the whole printed sheet from page primitives.

import { forwardRef, type ReactNode, useEffect, useImperativeHandle, useRef, useState } from "react";
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
  withMap: boolean;  // mini map at the bottom left (WallMap): the elevation avoids it
  download?: ReactNode;  // the Download menu, last in the first options row
}


export const ElevationStage = forwardRef<StageHandle, Props>(function ElevationStage({ elevation, withMap, download }, ref) {
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

  // Another wall or view: the same canvas, the whole wall
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
      <div className={ui.options}>
        <div className={ui.optionsRow}>
          <div className={ui.group}>
            <button aria-pressed={mode === "iso"} title={t("elevation.isoTitle")} onClick={toggleIso}>{t("elevation.iso")}</button>
          </div>
          {download}
        </div>
      </div>
      <div className={ui.toolbar}>
        <span className={ui.hint}>
          {elevation.height_assumed ? t("elevation.ceiling", { h: elevation.height }) : ""}
          {mode === "iso" ? t("elevation.isoHint") : t("elevation.hint")}
        </span>
        {/* In isometry screen mm differ by axis, so there is no scale bar */}
        {mode === "flat" && <ScaleBar zoom={zoom} />}
      </div>
    </>
  );
});
