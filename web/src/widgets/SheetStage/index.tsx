// Drawing area: the sheet in canvas (SheetView) or the wiring 3D, options at the top right, the hint below.
// Sheets with a plan share one drawing (drawing): a tab changes layers, the canvas and zoom stay.
// Routes are shown as the build computed them: there is no route editing in the viewer
// (decision 2026-11-16).

import { lazy, type ReactNode, Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { objectLayers, sceneOf, type Drawing } from "@/engine/sheet/drawing";
import { legendShown, wiringLegend } from "@/engine/sheet/legend";
import { ownLayers, viewOfLayer, wiringChains } from "@/engine/sheet/views";
import { lightLinks } from "@/engine/three/lightLinks";
import { SheetView } from "@/engine/sheet/SheetView";
import { WALL_MODES } from "@/shared/consts";
import { groupColors, PageIndex } from "@/shared/page";
import { useView, view } from "@/shared/store";
import ui from "@/shared/styles/ui.module.scss";
import type { Page } from "@/shared/types";
import type { Zoom } from "@/shared/zoom";
import { ButtonGroup, GroupButton } from "@/ui/ButtonGroup";
import { EmptyState } from "@/ui/EmptyState";
import { Icon } from "@/ui/Icon";
import { ScaleBar } from "@/ui/ScaleBar";
import { ZoomRail } from "@/ui/ZoomRail";
import { Filter3D } from "@/widgets/Filter3D";
import { Legend } from "@/widgets/Legend";
import type { Scene3DApi } from "@/widgets/Scene3D";
import { Tip } from "@/widgets/Tip";

// 3D (three.js) is a separate file, loaded the first time it is turned on
const Scene3D = lazy(() => import("@/widgets/Scene3D").then((m) => ({ default: m.Scene3D })));

// The lighting view: its cables (the electrical sheet) or what each switch turns on (the lighting
// sheet). The keys stay (the choice is remembered in the browser as light-mode), the labels do not
// repeat the "Wiring" and "Low voltage" views of the menu (decision 2026-11-16)
export const LIGHT_MODES = ["wiring", "links"] as const;
export type LightMode = (typeof LIGHT_MODES)[number];

interface Props {
  page: Page;
  drawing: Drawing;
  language?: string;             // project language (manifest), for the legend title
  download?: ReactNode;          // the Download menu, last in the first options row
  onWall?: (key: string) => void;  // open the elevation of a wall
  // The lighting view: "Wiring | Links" over the drawing; null when it is not the lighting view
  lightMode?: { mode: LightMode; onMode: (mode: LightMode) => void } | null;
}

export function SheetStage({ page, drawing, language, download, onWall, lightMode }: Props) {
  const { t } = useTranslation();
  const wrap = useRef<HTMLElement | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const sheet = useRef<SheetView | null>(null);
  const scene = useRef<Scene3DApi | null>(null);
  const index = useMemo(
    () => new PageIndex(page, drawing.objects, page.stage === "electrical" ? wiringChains(drawing) : {}),
    [page, drawing],
  );
  const [zoom, setZoom] = useState<Zoom>({ step: 0, label: "100%", pxPerMm: null });
  const [zoom3d, setZoom3d] = useState<Zoom>({ step: 0, label: "100%", pxPerMm: null });
  const [home, setHome] = useState(true);  // the 3D camera stands at the isometry
  const { show3d, wallMode } = useView((s) => s);
  // 3D belongs to the whole drawing (the wiring sheet scene); a tab shows what its layers show
  const scene3d = useMemo(() => sceneOf(drawing), [drawing]);
  const layerOf = useMemo(() => objectLayers(drawing), [drawing]);
  const electricalView = useView((s) => s.electricalView);
  const cables = useView((s) => s.cables);
  const own = useMemo(() => ownLayers(drawing, page, electricalView, cables), [drawing, page, electricalView, cables]);
  const links = useMemo(() => (scene3d ? lightLinks(drawing.pages.find((p) => p.stage === "lighting"), scene3d) : []),
    [drawing, scene3d]);
  // The wiring view shows everything, so its legend is full: points, boxes and lines (legend.ts)
  const legend = useMemo(() => (page.stage === "wiring"
    ? wiringLegend(drawing, page, { box: t("legend.box", { lng: language }), low: t("legend.low", { lng: language }) })
    : page.legend ?? []), [drawing, page, t, language]);
  const in3d = show3d && !!scene3d;
  const colors = useMemo(() => groupColors(drawing.pages), [drawing]);

  // The canvas is per drawing; a tab of the same drawing only calls setPage (below)
  const first = useRef({ page, index });
  first.current = { page, index };
  useEffect(() => {
    wrap.current = canvas.current!.parentElement;
    const sv = new SheetView(canvas.current!, wrap.current!, drawing, first.current.page, first.current.index);
    sv.onZoom = (z) => setZoom((p) => (p.step === z.step && p.pxPerMm === z.pxPerMm ? p : z));
    sheet.current = sv;
    return () => { sv.destroy(); sheet.current = null; };
  }, [drawing]);

  useEffect(() => {
    const sv = sheet.current;
    if (!sv || sv.page === page) return;
    sv.setPage(page, index);
  }, [page, index]);

  // Coming from an elevation or a question: the sheet opens right at the object (store.goto).
  // While it loads, the previous sheet is still here, so wait for the right one
  const goto = useView((s) => s.goto);
  useEffect(() => {
    if (!goto || page.stage !== goto.stage || !sheet.current) return;
    if (page.stage === "electrical") view.set({ electricalView: viewOfLayer(layerOf.get(goto.key)) });
    view.set({ goto: null });
    sheet.current.reveal(goto.key, goto.around);
  }, [drawing, page, goto, layerOf]);

  const toggle3d = () => view.set({ show3d: !show3d });

  const fit = () => (in3d ? scene.current?.fit() : sheet.current?.fit());

  let hint = `${page.format || ""} · ${t("sheet.hint")}`;
  if (in3d) {
    const a = scene3d!.assumed, notes = [];
    if (a.ceiling) notes.push(t("sheet.ceiling3d", { h: scene3d!.ceiling }));
    if (a.openings.length) notes.push(t("sheet.openings3d", { n: a.openings.length }));
    hint = [t("sheet.hint3d"), ...notes].join(" · ");
  }

  return (
    <>
      <canvas ref={canvas} tabIndex={0} aria-label={t("sheet.canvas")} />
      {in3d && (
        <Suspense fallback={<EmptyState className={ui.three}>{t("sheet.loading3d")}</EmptyState>}>
          <Scene3D scene={scene3d!} index={index} own={own} layerOf={layerOf} links={links} apiRef={scene} onZoom={setZoom3d} onHome={setHome} />
        </Suspense>
      )}
      <Tip index={index} onWall={onWall} colors={colors} />
      {!in3d && legend.length > 0 && (
        <Legend entries={legend.filter((e) => !own || legendShown(e, own))} language={language} />
      )}
      <ZoomRail zoom={in3d ? zoom3d : zoom} onFit={fit} fitLabel={t("sheet.fit")}
                onStep={(s) => (in3d ? scene.current?.zoomTo(s) : sheet.current?.zoomTo(s))} />
      <div className={ui.options}>
        <div className={ui.optionsRow}>
          {lightMode && (
            <ButtonGroup role="radiogroup" label={t("sheet.lightMode")}>
              {LIGHT_MODES.map((m) => (
                <GroupButton key={m} role="radio" aria-checked={lightMode.mode === m} pressed={lightMode.mode === m}
                        title={t(`sheet.lightModes.${m}Title`)}
                        onClick={() => lightMode.mode !== m && lightMode.onMode(m)}>{t(`sheet.lightModes.${m}`)}</GroupButton>
              ))}
            </ButtonGroup>
          )}
          {scene3d && (
            <ButtonGroup>
              <GroupButton pressed={in3d} onClick={toggle3d} title={t("sheet.title3d")}>3D</GroupButton>
            </ButtonGroup>
          )}
          {download}
        </div>
        {in3d && (
          <div className={ui.strip}>
            <ButtonGroup>
              {/* Grey and inactive while the view is at the isometry */}
              <GroupButton className={ui.home} disabled={home} aria-label={t("sheet.iso")}
                      title={t("sheet.iso")} onClick={() => scene.current?.iso()}><Icon name="home" /></GroupButton>
              {WALL_MODES.map((mode) => (
                <GroupButton key={mode} pressed={wallMode === mode} title={t("sheet.walls")}
                        onClick={() => view.set({ wallMode: mode })}>{t(`sheet.wallModes.${mode}`)}</GroupButton>
              ))}
            </ButtonGroup>
            <Filter3D scene={scene3d!} index={index} />
          </div>
        )}
      </div>
      <div className={ui.toolbar}>
        <span className={ui.hint}>{hint}</span>
        {!in3d && <ScaleBar zoom={zoom} />}
      </div>
    </>
  );
}
