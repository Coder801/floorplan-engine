// Область чертежа: лист в canvas (SheetView) или 3D проводки, кнопки под чертежом, подсказка.

import {
  forwardRef, lazy, Suspense, useEffect, useImperativeHandle, useMemo, useReducer, useRef, useState,
} from "react";
import { saveWiring } from "./api";
import { WALL_MODES } from "./consts";
import { PageIndex } from "./page";
import { SheetView } from "./sheet/SheetView";
import { useView, view } from "./store";
import type { Scene3DApi } from "./three/Scene3D";
import { Tip } from "./Tip";
import type { Page } from "./types";

// 3D (three.js) — отдельным файлом, грузится при первом включении
const Scene3D = lazy(() => import("./three/Scene3D").then((m) => ({ default: m.Scene3D })));

export interface StageHandle {
  pending(): number;              // несохранённые правки трасс
  downloadPng(filename: string): void;
}

interface Props {
  page: Page;
  project: string;
  onSaved: (notes: string[]) => void;
  onBanner: (text: string) => void;
}

const HINT = "колесо — масштаб, перетаскивание — сдвиг, двойной клик — к объекту или весь чертёж";
const EDIT_HINT = "Тяните участок линии или коробку · ⌘/Ctrl+клик — несколько участков · Esc — снять выделение";
const EDIT_TITLE = "Тяните участок линии: соседние участки удлиняются, углы остаются прямыми. "
  + "⌘/Ctrl+клик — выделить несколько участков. Коробка на стене ездит вдоль стены, "
  + "на потолке — свободно. Потребители и щит не двигаются.";

export const SheetStage = forwardRef<StageHandle, Props>(function SheetStage({ page, project, onSaved, onBanner }, ref) {
  const wrap = useRef<HTMLElement | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const sheet = useRef<SheetView | null>(null);
  const scene = useRef<Scene3DApi | null>(null);
  const index = useMemo(() => new PageIndex(page), [page]);
  const [zoom, setZoom] = useState("100%");
  const [saving, setSaving] = useState(false);
  const [, tick] = useReducer((n: number) => n + 1, 0);  // правка изменилась — перерисовать кнопки
  const { editMode, show3d, wallMode } = useView((s) => s);
  const in3d = show3d && !!page.scene;

  useEffect(() => {
    wrap.current = canvas.current!.parentElement;
    const sv = new SheetView(canvas.current!, wrap.current!, page, index);
    sv.onEditChange = tick;
    sv.onZoom = setZoom;
    sheet.current = sv;
    tick();  // лист создан после первого рендера — показать его кнопки правки
    return () => { sv.destroy(); sheet.current = null; };
  }, [page, index]);

  useImperativeHandle(ref, () => ({
    pending: () => (sheet.current && !sheet.current.saved && sheet.current.ed ? sheet.current.ed.pending() : 0),
    downloadPng: (f) => sheet.current?.downloadPng(f),
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
    const a = page.scene!.assumed, notes = [];
    if (a.ceiling) notes.push(`потолок ${page.scene!.ceiling} — допущение`);
    if (a.openings.length) notes.push(`высоты проёмов (${a.openings.length}) — типовые`);
    hint = ["левая кнопка — вращать, правая — сдвиг, колесо — масштаб, двойной клик — к линии", ...notes].join(" · ");
  } else if (editMode && ed) hint = saving ? "Сохраняю и пересобираю…" : EDIT_HINT;

  const n = ed?.pending() ?? 0, back = ed?.resettable();
  return (
    <>
      <canvas ref={canvas} tabIndex={0} aria-label="Чертёж листа" />
      {in3d && (
        <Suspense fallback={<div className="three empty">Загружаю 3D…</div>}>
          <Scene3D scene={page.scene!} index={index} apiRef={scene} onZoom={setZoom} />
        </Suspense>
      )}
      <Tip index={index} />
      <div className="zoom">
        <div className="group">
          <button aria-label="Уменьшить" onClick={() => zoomBy(1 / 1.25)}>−</button>
          <span className="mono" style={{ padding: "0 8px", display: "flex", alignItems: "center" }}>{zoom}</span>
          <button aria-label="Увеличить" onClick={() => zoomBy(1.25)}>+</button>
          <button onClick={fit}>Весь чертёж</button>
        </div>
        {page.scene && (
          <div className="group">
            <button aria-pressed={in3d} onClick={toggle3d}
                    title="Проводка в объёме: трассы по потолку и полу, спуски к точкам">3D</button>
            {in3d && <button onClick={() => scene.current?.iso()}>Изометрия</button>}
            {in3d && WALL_MODES.map(([mode, label]) => (
              <button key={mode} aria-pressed={wallMode === mode} title="Стены"
                      onClick={() => view.set({ wallMode: mode })}>{label}</button>
            ))}
          </div>
        )}
        {ed && !in3d && (
          <div className="group">
            <button aria-pressed={editMode} title={EDIT_TITLE} onClick={toggleEdit}>Править трассы</button>
            {editMode && (
              <>
                <button className={n ? "primary" : undefined} disabled={!n || saving}
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
        <span className="small muted">{hint}</span>
      </div>
    </>
  );
});
