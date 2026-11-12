// Drawing area: the sheet in canvas (SheetView) or the wiring 3D, options at the top right, the hint below.
// Sheets with a plan share one drawing (drawing): a tab changes layers, the canvas and zoom stay.

import {
  forwardRef, lazy, type ReactNode, Suspense, useEffect, useImperativeHandle, useMemo, useReducer, useRef, useState,
} from "react";
import { useTranslation } from "react-i18next";
import { objectLayers, sceneOf, type Drawing } from "@/engine/sheet/drawing";
import { legendShown, wiringLegend } from "@/engine/sheet/legend";
import { ownLayers, systemOf, viewOfLayer, wiringChains } from "@/engine/sheet/views";
import { lightLinks } from "@/engine/three/lightLinks";
import { SheetView } from "@/engine/sheet/SheetView";
import { saveWiring } from "@/shared/api";
import { WALL_MODES } from "@/shared/consts";
import { PageIndex } from "@/shared/page";
import { SYSTEMS, useView, view, type System } from "@/shared/store";
import ui from "@/shared/styles/ui.module.scss";
import type { Page } from "@/shared/types";
import type { Zoom } from "@/shared/zoom";
import { Button } from "@/ui/Button";
import { ButtonGroup } from "@/ui/ButtonGroup";
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

// The lighting view: its lines (the electrical sheet) or its links (the lighting sheet)
export const LIGHT_MODES = ["wiring", "links"] as const;
export type LightMode = (typeof LIGHT_MODES)[number];

// The label of a system is the label of its view
const SYSTEM_VIEW = { light: "lighting", sockets: "electrical", low: "low" } as const satisfies Record<System, string>;

export interface StageHandle {
  pending(): number;              // unsaved route edits
}

interface Props {
  page: Page;
  drawing: Drawing;
  project: string;
  language?: string;             // project language (manifest), for the legend title
  editable?: boolean;            // routes may be edited (no for a studio client: no button)
  download?: ReactNode;          // the Download menu, last in the first options row
  onWall?: (key: string) => void;  // open the elevation of a wall
  onSaved: (notes: string[]) => void;
  onBusy?: (busy: boolean) => void;  // saving and rebuilding in progress: the page blocks the interface
  onBanner: (text: string) => void;
  // The lighting view: "Wiring | Links" over the drawing; null when it is not the lighting view
  lightMode?: { mode: LightMode; onMode: (mode: LightMode) => void } | null;
}


export const SheetStage = forwardRef<StageHandle, Props>(function SheetStage({ page, drawing, project, language, editable = true, download, onWall, onSaved, onBusy, onBanner, lightMode }, ref) {
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
  const [saving, setSaving] = useState(false);
  const [home, setHome] = useState(true);  // the 3D camera stands at the isometry
  const [, tick] = useReducer((n: number) => n + 1, 0);  // the edit changed: redraw the buttons
  const { editMode, show3d, wallMode } = useView((s) => s);
  // 3D belongs to the whole drawing (the wiring sheet scene); a tab shows what its layers show
  const scene3d = useMemo(() => sceneOf(drawing), [drawing]);
  const layerOf = useMemo(() => objectLayers(drawing), [drawing]);
  const electricalView = useView((s) => s.electricalView);
  const cables = useView((s) => s.cables);
  const systemsOff = useView((s) => s.systemsOff);
  const own = useMemo(() => ownLayers(drawing, page, electricalView, cables, systemsOff),
    [drawing, page, electricalView, cables, systemsOff]);
  const links = useMemo(() => (scene3d ? lightLinks(drawing.pages.find((p) => p.stage === "lighting"), scene3d) : []),
    [drawing, scene3d]);
  // The wiring view shows everything, so its legend is full: points, boxes and lines (legend.ts)
  const legend = useMemo(() => (page.stage === "wiring"
    ? wiringLegend(drawing, page, { box: t("legend.box", { lng: language }), low: t("legend.low", { lng: language }) })
    : page.legend ?? []), [drawing, page, t, language]);
  // Systems of the wiring sheet, each a chip over the drawing (one system has nothing to switch)
  const systems = useMemo(() => {
    const layers = page.stage === "wiring" ? [...(drawing.own.get(page) ?? [])] : [];
    const has = SYSTEMS.filter((sys) => layers.some((l) => systemOf(l) === sys));
    return has.length > 1 ? has : [];
  }, [drawing, page]);
  const in3d = show3d && !!scene3d;

  // The canvas is per drawing; a tab of the same drawing only calls setPage (below)
  const first = useRef({ page, index });
  first.current = { page, index };
  useEffect(() => {
    wrap.current = canvas.current!.parentElement;
    const sv = new SheetView(canvas.current!, wrap.current!, drawing, first.current.page, first.current.index);
    sv.onEditChange = tick;
    sv.onZoom = (z) => setZoom((p) => (p.step === z.step && p.pxPerMm === z.pxPerMm ? p : z));
    sheet.current = sv;
    tick();  // the sheet was created after the first render: show its edit buttons
    return () => { sv.destroy(); sheet.current = null; };
  }, [drawing]);

  useEffect(() => {
    const sv = sheet.current;
    if (!sv || sv.page === page) return;
    sv.setPage(page, index);
    setSaving(false);
    tick();
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

  useImperativeHandle(ref, () => ({
    pending: () => (sheet.current && !sheet.current.saved && sheet.current.ed ? sheet.current.ed.pending() : 0),
  }), []);

  const sv = sheet.current, ed = sv?.ed ?? null;

  // Route editing works on every line: the systems switched off come back
  const toggleEdit = () => {
    view.set({ editMode: !editMode, ...(editMode ? {} : { systemsOff: new Set<System>() }) });
    sheet.current?.editModeChanged();
  };
  const toggleSystem = (sys: System) => {
    const off = new Set(systemsOff);
    if (off.has(sys)) off.delete(sys); else off.add(sys);
    view.set({ systemsOff: off, selected: null, neighbors: null, pinned: null, tip: null });
  };
  const toggle3d = () => {
    ed?.clearSelection();
    view.set({ show3d: !show3d });
    tick();
  };

  // POST the edits → wiring.yaml and a rebuild; then the sheet is reloaded
  const save = async () => {
    if (!sv || !ed) return;
    const body = ed.payload();
    if (!Object.keys(body.wires).length && !Object.keys(body.boxes).length) {
      ed.sel.clear(); tick(); sv.draw();
      return;
    }
    sv.saved = true; setSaving(true); onBusy?.(true);
    try {
      const answer = await saveWiring(project, body);
      onSaved(answer.notes || []);
    } catch (e) {
      sv.saved = false; setSaving(false); onBusy?.(false);
      onBanner(t("sheet.saveFailed", { message: (e as Error).message }));
    }
  };
  const reset = () => { ed?.reset(); save(); };

  const fit = () => (in3d ? scene.current?.fit() : sv?.fit());

  let hint = `${page.format || ""} · ${t("sheet.hint")}`;
  if (in3d) {
    const a = scene3d!.assumed, notes = [];
    if (a.ceiling) notes.push(t("sheet.ceiling3d", { h: scene3d!.ceiling }));
    if (a.openings.length) notes.push(t("sheet.openings3d", { n: a.openings.length }));
    hint = [t("sheet.hint3d"), ...notes].join(" · ");
  } else if (editMode && ed) hint = saving ? t("sheet.saving") : t("sheet.editHint");

  const n = ed?.pending() ?? 0, back = ed?.resettable();
  return (
    <>
      <canvas ref={canvas} tabIndex={0} aria-label={t("sheet.canvas")} />
      {in3d && (
        <Suspense fallback={<EmptyState className={ui.three}>{t("sheet.loading3d")}</EmptyState>}>
          <Scene3D scene={scene3d!} index={index} own={own} layerOf={layerOf} links={links} apiRef={scene} onZoom={setZoom3d} onHome={setHome} />
        </Suspense>
      )}
      <Tip index={index} onWall={onWall} />
      {!in3d && legend.length > 0 && (
        <Legend entries={legend.filter((e) => !own || legendShown(e, own))} language={language} />
      )}
      <ZoomRail zoom={in3d ? zoom3d : zoom} onFit={fit} fitLabel={t("sheet.fit")}
                onStep={(s) => (in3d ? scene.current?.zoomTo(s) : sv?.zoomTo(s))} />
      <div className={ui.options}>
        <div className={ui.optionsRow}>
          {lightMode && (
            <ButtonGroup role="radiogroup" label={t("sheet.lightMode")}>
              {LIGHT_MODES.map((m) => (
                <Button key={m} variant="bare" role="radio" aria-checked={lightMode.mode === m} pressed={lightMode.mode === m}
                        title={t(`sheet.lightModes.${m}Title`)}
                        onClick={() => lightMode.mode !== m && lightMode.onMode(m)}>{t(`sheet.lightModes.${m}`)}</Button>
              ))}
            </ButtonGroup>
          )}
          {systems.length > 0 && !(editMode && ed) && (
            <ButtonGroup label={t("sheet.systems")}>
              {systems.map((sys) => (
                <Button key={sys} variant="bare" pressed={!systemsOff.has(sys)} title={t("sheet.systemsTitle")}
                        onClick={() => toggleSystem(sys)}>{t(`views.${SYSTEM_VIEW[sys]}`)}</Button>
              ))}
            </ButtonGroup>
          )}
          {ed && !in3d && editable && (
            <ButtonGroup>
              <Button variant="bare" pressed={editMode} title={t("sheet.editTitle")} onClick={toggleEdit}>{t("sheet.edit")}</Button>
            </ButtonGroup>
          )}
          {scene3d && (
            <ButtonGroup>
              <Button variant="bare" pressed={in3d} onClick={toggle3d} title={t("sheet.title3d")}>3D</Button>
            </ButtonGroup>
          )}
          {download}
        </div>
        {in3d && (
          <div className={ui.strip}>
            <ButtonGroup>
              {/* Grey and inactive while the view is at the isometry */}
              <Button variant="bare" className={ui.home} disabled={home} aria-label={t("sheet.iso")}
                      title={t("sheet.iso")} onClick={() => scene.current?.iso()}><Icon name="home" /></Button>
              {WALL_MODES.map((mode) => (
                <Button key={mode} variant="bare" pressed={wallMode === mode} title={t("sheet.walls")}
                        onClick={() => view.set({ wallMode: mode })}>{t(`sheet.wallModes.${mode}`)}</Button>
              ))}
            </ButtonGroup>
            <Filter3D scene={scene3d!} index={index} />
          </div>
        )}
        {ed && !in3d && editable && editMode && (
          <div className={ui.strip}>
            <ButtonGroup>
              <Button variant={n ? "primary" : "bare"} disabled={!n || saving}
                      title={t("sheet.saveTitle")} onClick={save}>
                {n ? t("sheet.saveN", { n }) : t("sheet.save")}
              </Button>
              <Button variant="bare" disabled={!ed.history.length} title={t("sheet.undoTitle")}
                      onClick={() => sv?.undo()}>{t("sheet.undo")}</Button>
              <Button variant="bare" disabled={!(back && (back.wires.length || back.box)) || saving}
                      title={t("sheet.autoTitle")}
                      onClick={reset}>{t("sheet.auto")}</Button>
            </ButtonGroup>
          </div>
        )}
      </div>
      <div className={ui.toolbar}>
        <span className={ui.hint}>{hint}</span>
        {!in3d && <ScaleBar zoom={zoom} />}
      </div>
    </>
  );
});
