// Wall elevation: its own canvas (ElevationView) from the elevation data, zoom buttons;
// "Isometry" shows the wall at 45° with part of the neighbouring one at the corner (the choice
// is remembered in the browser). Not the shared drawing of plan sheets: no sheet layers, no
// wall and room highlighting, no 3D; electrical and water are toggled with the eye in "On the
// wall" (store.wallLayers). A click on a junction box pins it and shows its hint with the box
// scheme, as on the wiring sheet (Tip; the card comes from the page objects).
// The album PNG comes from "Download" (Viewer): the whole printed sheet from page primitives.

import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ElevationView, type ElevMode } from "@/engine/elevation/ElevationView";
import { PageIndex } from "@/shared/page";
import { remember, remembered } from "@/shared/palette";
import { useView } from "@/shared/store";
import ui from "@/shared/styles/ui.module.scss";
import type { Elevation, Page } from "@/shared/types";
import type { Zoom } from "@/shared/zoom";
import { ButtonGroup, GroupButton } from "@/ui/ButtonGroup";
import { ScaleBar } from "@/ui/ScaleBar";
import { ZoomRail } from "@/ui/ZoomRail";
import { Tip } from "@/widgets/Tip";

interface Props {
  elevation: Elevation;
  withMap: boolean;  // mini map at the bottom left (WallMap): the elevation avoids it
  download?: ReactNode;  // the Download menu, last in the first options row
  page?: Page;  // the elevations sheet: cards of its boxes for the hint
}

// Group colours of the wall (its points and boxes), for the box scheme
function wallColors(e: Elevation): Record<string, string> {
  const out: Record<string, string> = {};
  for (const o of [...e.points, ...e.boxes]) if (o.group && o.color) out[o.group] = o.color;
  return out;
}


export function ElevationStage({ elevation, withMap, download, page }: Props) {
  const { t } = useTranslation();
  const canvas = useRef<HTMLCanvasElement>(null);
  const ev = useRef<ElevationView | null>(null);
  const [zoom, setZoom] = useState<Zoom>({ step: 0, label: "100%", pxPerMm: null });
  const [mode, setMode] = useState<ElevMode>(() => (remembered("elevMode") === "iso" ? "iso" : "flat"));
  const pinned = useView((s) => s.pinned);
  const index = useMemo(() => (page ? new PageIndex(page) : null), [page]);
  const colors = useMemo(() => wallColors(elevation), [elevation]);
  // A row of the box scheme opens another box of this wall; the rest are on other walls
  const here = useMemo(() => new Set(elevation.boxes.map((b) => b.key)), [elevation]);
  const boxTip = !!index && !!pinned && here.has(pinned) && !!page?.objects?.[pinned];
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

  return (
    <>
      <canvas ref={canvas} tabIndex={0} aria-label={t("elevation.canvas", { title: elevation.title })} />
      {boxTip && <Tip index={index!} colors={colors} canOpen={(o) => here.has(o) && !!page?.objects?.[o]} />}
      <ZoomRail zoom={zoom} onStep={(s) => ev.current?.zoomTo(s)} onFit={() => ev.current?.fit()} fitLabel={t("elevation.fit")} />
      <div className={ui.options}>
        <div className={ui.optionsRow}>
          <ButtonGroup>
            <GroupButton pressed={mode === "iso"} title={t("elevation.isoTitle")} onClick={toggleIso}>{t("elevation.iso")}</GroupButton>
          </ButtonGroup>
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
}
