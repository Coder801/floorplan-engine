// Drawing area: the sheet in canvas (SheetView) or the wiring 3D, options at the top right, the hint below.
// Sheets with a plan share one drawing (drawing): a tab changes layers, the canvas and zoom stay.

import {
  forwardRef, lazy, type ReactNode, Suspense, useEffect, useImperativeHandle, useMemo, useReducer, useRef, useState,
} from "react";
import { useTranslation } from "react-i18next";
import { objectLayers, sceneOf, type Drawing } from "@/engine/sheet/drawing";
import { ownLayers, viewOfLayer, wiringChains } from "@/engine/sheet/views";
import { SheetView } from "@/engine/sheet/SheetView";
import { saveWiring } from "@/shared/api";
import { WALL_MODES } from "@/shared/consts";
import { cx } from "@/shared/cx";
import { PageIndex } from "@/shared/page";
import { useView, view } from "@/shared/store";
import ui from "@/shared/styles/ui.module.scss";
import type { Page } from "@/shared/types";
import type { Zoom } from "@/shared/zoom";
import { Icon } from "@/ui/Icon";
import { ScaleBar } from "@/ui/ScaleBar";
import { ZoomRail } from "@/ui/ZoomRail";
import { Filter3D } from "@/widgets/Filter3D";
import { Legend } from "@/widgets/Legend";
import type { Scene3DApi } from "@/widgets/Scene3D";
import { Tip } from "@/widgets/Tip";

// 3D (three.js) is a separate file, loaded the first time it is turned on
const Scene3D = lazy(() => import("@/widgets/Scene3D").then((m) => ({ default: m.Scene3D })));

export interface StageHandle {
  pending(): number;              // unsaved route edits
}

interface Props {
  page: Page;
  drawing: Drawing;
  project: string;
  language?: string;             // project language (manifest), for the legend title
  onStage?: (stage: string) => void;  // open the sheet of a topic: the object is on another view
  editable?: boolean;            // routes may be edited (no for a studio client: no button)
  download?: ReactNode;          // the Download menu, last in the first options row
  onWall?: (key: string) => void;  // open the elevation of a wall
  onSaved: (notes: string[]) => void;
  onBusy?: (busy: boolean) => void;  // saving and rebuilding in progress: the page blocks the interface
  onBanner: (text: string) => void;
}


export const SheetStage = forwardRef<StageHandle, Props>(function SheetStage({ page, drawing, project, language, editable = true, download, onWall, onSaved, onBusy, onBanner, onStage }, ref) {
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
  const own = useMemo(() => ownLayers(drawing, page, electricalView), [drawing, page, electricalView]);
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
    if (page.stage === "electrical") {  // light is not on the electrical sheet any more
      const target = viewOfLayer(layerOf.get(goto.key));
      if (target === "lighting") { view.set({ goto: { ...goto, stage: target } }); onStage?.(target); return; }
      view.set({ electricalView: target });
    }
    view.set({ goto: null });
    sheet.current.reveal(goto.key, goto.around);
  }, [drawing, page, goto, layerOf, onStage]);

  useImperativeHandle(ref, () => ({
    pending: () => (sheet.current && !sheet.current.saved && sheet.current.ed ? sheet.current.ed.pending() : 0),
  }), []);

  const sv = sheet.current, ed = sv?.ed ?? null;

  const toggleEdit = () => {
    view.set({ editMode: !editMode });
    sheet.current?.editModeChanged();
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
        <Suspense fallback={<div className={cx(ui.three, ui.empty)}>{t("sheet.loading3d")}</div>}>
          <Scene3D scene={scene3d!} index={index} own={own} layerOf={layerOf} apiRef={scene} onZoom={setZoom3d} onHome={setHome} />
        </Suspense>
      )}
      <Tip index={index} onWall={onWall} />
      {!in3d && page.legend && (
        <Legend entries={page.legend.filter((e) => !own || e.items.some((i) => own.has(i.l)))} language={language} />
      )}
      <ZoomRail zoom={in3d ? zoom3d : zoom} onFit={fit} fitLabel={t("sheet.fit")}
                onStep={(s) => (in3d ? scene.current?.zoomTo(s) : sv?.zoomTo(s))} />
      <div className={ui.options}>
        <div className={ui.optionsRow}>
          {ed && !in3d && editable && (
            <div className={ui.group}>
              <button aria-pressed={editMode} title={t("sheet.editTitle")} onClick={toggleEdit}>{t("sheet.edit")}</button>
            </div>
          )}
          {scene3d && (
            <div className={ui.group}>
              <button aria-pressed={in3d} onClick={toggle3d}
                      title={t("sheet.title3d")}>3D</button>
            </div>
          )}
          {download}
        </div>
        {in3d && (
          <div className={ui.strip}>
            <div className={ui.group}>
              {/* Grey and inactive while the view is at the isometry */}
              <button className={ui.home} disabled={home} aria-label={t("sheet.iso")}
                      title={t("sheet.iso")} onClick={() => scene.current?.iso()}><Icon name="home" /></button>
              {WALL_MODES.map((mode) => (
                <button key={mode} aria-pressed={wallMode === mode} title={t("sheet.walls")}
                        onClick={() => view.set({ wallMode: mode })}>{t(`sheet.wallModes.${mode}`)}</button>
              ))}
            </div>
            <Filter3D scene={scene3d!} index={index} />
          </div>
        )}
        {ed && !in3d && editable && editMode && (
          <div className={ui.strip}>
            <div className={ui.group}>
              <button className={cx(!!n && ui.primary)} disabled={!n || saving}
                      title={t("sheet.saveTitle")} onClick={save}>
                {n ? t("sheet.saveN", { n }) : t("sheet.save")}
              </button>
              <button disabled={!ed.history.length} title={t("sheet.undoTitle")}
                      onClick={() => sv?.undo()}>{t("sheet.undo")}</button>
              <button disabled={!(back && (back.wires.length || back.box)) || saving}
                      title={t("sheet.autoTitle")}
                      onClick={reset}>{t("sheet.auto")}</button>
            </div>
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
