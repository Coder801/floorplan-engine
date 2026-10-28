// Область чертежа: лист в canvas (SheetView) или 3D проводки, кнопки под чертежом, подсказка.
// Чертёж один на листы с планом (drawing): вкладка меняет слои, холст и масштаб остаются.

import {
  forwardRef, lazy, Suspense, useEffect, useImperativeHandle, useMemo, useReducer, useRef, useState,
} from "react";
import { saveWiring } from "./api";
import { WALL_MODES } from "./consts";
import { Filter3D } from "./Filter3D";
import { PageIndex } from "./page";
import { objectLayers, sceneOf, type Drawing } from "./sheet/drawing";
import { SheetView } from "./sheet/SheetView";
import { cx } from "./cx";
import { useView, view } from "./store";
import ui from "./styles/ui.module.scss";
import type { Scene3DApi } from "./three/Scene3D";
import { Tip } from "./Tip";
import type { Page } from "./types";

// 3D (three.js) — отдельным файлом, грузится при первом включении
const Scene3D = lazy(() => import("./three/Scene3D").then((m) => ({ default: m.Scene3D })));

export interface StageHandle {
  pending(): number;              // несохранённые правки трасс
}

interface Props {
  page: Page;
  drawing: Drawing;
  project: string;
  onSaved: (notes: string[]) => void;
  onBanner: (text: string) => void;
}

const HINT = "колесо — масштаб, перетаскивание — сдвиг, двойной клик — к объекту или весь чертёж";
const EDIT_HINT = "Тяните участок линии или коробку · ⌘/Ctrl+клик — несколько участков · Esc — снять выделение";
const EDIT_TITLE = "Тяните участок линии: соседние участки удлиняются, углы остаются прямыми. "
  + "⌘/Ctrl+клик — выделить несколько участков. Коробка на стене ездит вдоль стены, "
  + "на потолке — свободно. Потребители и щит не двигаются.";

export const SheetStage = forwardRef<StageHandle, Props>(function SheetStage({ page, drawing, project, onSaved, onBanner }, ref) {
  const wrap = useRef<HTMLElement | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const sheet = useRef<SheetView | null>(null);
  const scene = useRef<Scene3DApi | null>(null);
  const index = useMemo(() => new PageIndex(page, drawing.objects), [page, drawing]);
  const [zoom, setZoom] = useState("100%");
  const [saving, setSaving] = useState(false);
  const [, tick] = useReducer((n: number) => n + 1, 0);  // правка изменилась — перерисовать кнопки
  const { editMode, show3d, wallMode } = useView((s) => s);
  // 3D — у всего чертежа (сцена листа проводки); на вкладке видно то же, что в её слоях
  const scene3d = useMemo(() => sceneOf(drawing), [drawing]);
  const layerOf = useMemo(() => objectLayers(drawing), [drawing]);
  const own = drawing.own.get(page) ?? null;
  const in3d = show3d && !!scene3d;

  // Холст — на чертёж; вкладка того же чертежа — только setPage (ниже)
  const first = useRef({ page, index });
  first.current = { page, index };
  useEffect(() => {
    wrap.current = canvas.current!.parentElement;
    const sv = new SheetView(canvas.current!, wrap.current!, drawing, first.current.page, first.current.index);
    sv.onEditChange = tick;
    sv.onZoom = setZoom;
    sheet.current = sv;
    tick();  // лист создан после первого рендера — показать его кнопки правки
    return () => { sv.destroy(); sheet.current = null; };
  }, [drawing]);

  useEffect(() => {
    const sv = sheet.current;
    if (!sv || sv.page === page) return;
    sv.setPage(page, index);
    setSaving(false);
    tick();
  }, [page, index]);

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

  // POST правок → wiring.yaml и пересборка; затем лист перечитывается
  const save = async () => {
    if (!sv || !ed) return;
    const body = ed.payload();
    if (!Object.keys(body.wires).length && !Object.keys(body.boxes).length) {
      ed.sel.clear(); tick(); sv.draw();
      return;
    }
    sv.saved = true; setSaving(true);
    try {
      const answer = await saveWiring(project, body);
      onSaved(answer.notes || []);
    } catch (e) {
      sv.saved = false; setSaving(false);
      onBanner(`Правки трасс не сохранены — ${(e as Error).message}`);
    }
  };
  const reset = () => { ed?.reset(); save(); };

  const zoomBy = (f: number) => (in3d ? scene.current?.zoomBy(f) : sv?.zoomBy(f));
  const fit = () => (in3d ? scene.current?.fit() : sv?.fit());

  let hint = `${page.format || ""} · ${HINT}`;
  if (in3d) {
    const a = scene3d!.assumed, notes = [];
    if (a.ceiling) notes.push(`потолок ${scene3d!.ceiling} — допущение`);
    if (a.openings.length) notes.push(`высоты проёмов (${a.openings.length}) — типовые`);
    hint = ["левая кнопка — вращать, правая — сдвиг, колесо — масштаб, двойной клик — к объекту", ...notes].join(" · ");
  } else if (editMode && ed) hint = saving ? "Сохраняю и пересобираю…" : EDIT_HINT;

  const n = ed?.pending() ?? 0, back = ed?.resettable();
  return (
    <>
      <canvas ref={canvas} tabIndex={0} aria-label="Чертёж листа" />
      {in3d && (
        <Suspense fallback={<div className={cx(ui.three, ui.empty)}>Загружаю 3D…</div>}>
          <Scene3D scene={scene3d!} index={index} own={own} layerOf={layerOf} apiRef={scene} onZoom={setZoom} />
        </Suspense>
      )}
      <Tip index={index} />
      <div className={ui.toolbar}>
        <div className={ui.group}>
          <button aria-label="Уменьшить" onClick={() => zoomBy(1 / 1.25)}>−</button>
          <span className={cx(ui.zoomValue, "mono")}>{zoom}</span>
          <button aria-label="Увеличить" onClick={() => zoomBy(1.25)}>+</button>
          <button onClick={fit}>Весь чертёж</button>
        </div>
        {scene3d && (
          <div className={ui.group}>
            <button aria-pressed={in3d} onClick={toggle3d}
                    title="Проводка в объёме: трассы по потолку и полу, спуски к точкам">3D</button>
            {in3d && <button onClick={() => scene.current?.iso()}>Изометрия</button>}
            {in3d && WALL_MODES.map(([mode, label]) => (
              <button key={mode} aria-pressed={wallMode === mode} title="Стены"
                      onClick={() => view.set({ wallMode: mode })}>{label}</button>
            ))}
          </div>
        )}
        {in3d && <Filter3D scene={scene3d!} index={index} />}
        {ed && !in3d && (
          <div className={ui.group}>
            <button aria-pressed={editMode} title={EDIT_TITLE} onClick={toggleEdit}>Править трассы</button>
            {editMode && (
              <>
                <button className={cx(!!n && ui.primary)} disabled={!n || saving}
                        title="Записать в wiring.yaml и пересобрать проект" onClick={save}>
                  {n ? `Сохранить (${n})` : "Сохранить"}
                </button>
                <button disabled={!ed.history.length} title="⌘/Ctrl+Z — шаг назад"
                        onClick={() => sv?.undo()}>Отменить</button>
                <button disabled={!(back && (back.wires.length || back.box)) || saving}
                        title="Выделенные линии и выбранную коробку — снова как строит программа; сохраняет сразу"
                        onClick={reset}>Автотрасса</button>
              </>
            )}
          </div>
        )}
        <span className={ui.hint}>{hint}</span>
      </div>
    </>
  );
});
