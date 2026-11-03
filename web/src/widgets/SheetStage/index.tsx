// Drawing area: the sheet in canvas (SheetView) or the wiring 3D, buttons under the drawing, the hint.
// Sheets with a plan share one drawing (drawing): a tab changes layers, the canvas and zoom stay.

import {
  forwardRef, lazy, Suspense, useEffect, useImperativeHandle, useMemo, useReducer, useRef, useState,
} from "react";
import { useTranslation } from "react-i18next";
import { objectLayers, sceneOf, type Drawing } from "@/engine/sheet/drawing";
import { SheetView } from "@/engine/sheet/SheetView";
import { saveWiring } from "@/shared/api";
import { WALL_MODES } from "@/shared/consts";
import { cx } from "@/shared/cx";
import { PageIndex } from "@/shared/page";
import { useView, view } from "@/shared/store";
import ui from "@/shared/styles/ui.module.scss";
import type { Page } from "@/shared/types";
import type { Zoom } from "@/shared/zoom";
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
  editable?: boolean;            // routes may be edited (no for a studio client: no button)
  onSaved: (notes: string[]) => void;
  onBusy?: (busy: boolean) => void;  // saving and rebuilding in progress: the page blocks the interface
  onBanner: (text: string) => void;
}


export const SheetStage = forwardRef<StageHandle, Props>(function SheetStage({ page, drawing, project, editable = true, onSaved, onBusy, onBanner }, ref) {
  const { t } = useTranslation();
  const wrap = useRef<HTMLElement | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const sheet = useRef<SheetView | null>(null);
  const scene = useRef<Scene3DApi | null>(null);
  const index = useMemo(() => new PageIndex(page, drawing.objects), [page, drawing]);
  const [zoom, setZoom] = useState<Zoom>({ step: 0, label: "100%", pxPerMm: null });
  const [zoom3d, setZoom3d] = useState<Zoom>({ step: 0, label: "100%", pxPerMm: null });
  const [saving, setSaving] = useState(false);
  const [, tick] = useReducer((n: number) => n + 1, 0);  // the edit changed: redraw the buttons
  const { editMode, show3d, wallMode } = useView((s) => s);
  // 3D belongs to the whole drawing (the wiring sheet scene); a tab shows what its layers show
  const scene3d = useMemo(() => sceneOf(drawing), [drawing]);
  const layerOf = useMemo(() => objectLayers(drawing), [drawing]);
  const own = drawing.own.get(page) ?? null;
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

  // Coming from an elevation: the wiring sheet opens right at the point's line (store.goto).
  // While it loads, the previous sheet is still here, so wait for wiring
  useEffect(() => {
    const goto = view.get().goto;
    if (!goto || page.stage !== "wiring" || !sheet.current) return;
    view.set({ goto: null });
    sheet.current.reveal(goto);
  }, [drawing, page]);

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
          <Scene3D scene={scene3d!} index={index} own={own} layerOf={layerOf} apiRef={scene} onZoom={setZoom3d} />
        </Suspense>
      )}
      <Tip index={index} />
      {!in3d && page.legend && <Legend entries={page.legend} />}
      <ZoomRail zoom={in3d ? zoom3d : zoom} onFit={fit} fitLabel={t("sheet.fit")}
                onStep={(s) => (in3d ? scene.current?.zoomTo(s) : sv?.zoomTo(s))} />
      <div className={ui.toolbar}>
        {scene3d && (
          <div className={ui.group}>
            <button aria-pressed={in3d} onClick={toggle3d}
                    title={t("sheet.title3d")}>3D</button>
            {in3d && <button onClick={() => scene.current?.iso()}>{t("sheet.iso")}</button>}
            {in3d && WALL_MODES.map((mode) => (
              <button key={mode} aria-pressed={wallMode === mode} title={t("sheet.walls")}
                      onClick={() => view.set({ wallMode: mode })}>{t(`sheet.wallModes.${mode}`)}</button>
            ))}
          </div>
        )}
        {in3d && <Filter3D scene={scene3d!} index={index} />}
        {ed && !in3d && editable && (
          <div className={ui.group}>
            <button aria-pressed={editMode} title={t("sheet.editTitle")} onClick={toggleEdit}>{t("sheet.edit")}</button>
            {editMode && (
              <>
                <button className={cx(!!n && ui.primary)} disabled={!n || saving}
                        title={t("sheet.saveTitle")} onClick={save}>
                  {n ? t("sheet.saveN", { n }) : t("sheet.save")}
                </button>
                <button disabled={!ed.history.length} title={t("sheet.undoTitle")}
                        onClick={() => sv?.undo()}>{t("sheet.undo")}</button>
                <button disabled={!(back && (back.wires.length || back.box)) || saving}
                        title={t("sheet.autoTitle")}
                        onClick={reset}>{t("sheet.auto")}</button>
              </>
            )}
          </div>
        )}
        <span className={ui.hint}>{hint}</span>
        {!in3d && <ScaleBar zoom={zoom} />}
      </div>
    </>
  );
});
