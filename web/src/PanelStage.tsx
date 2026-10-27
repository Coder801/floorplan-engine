// Лист «Щит»: щит в лицо в своём canvas (PanelView) из данных щита, кнопки масштаба
// и слабые места под чертежом, карточка аппарата по клику (DeviceCard). PNG для альбома —
// весь лист из примитивов страницы.

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { DeviceCard } from "./panel/DeviceCard";
import { PanelView } from "./panel/PanelView";
import { downloadSheetPng } from "./sheet/paint";
import type { StageHandle } from "./SheetStage";
import type { Page, PanelData } from "./types";

interface Props {
  page: Page;
  panel: PanelData;
}

const HINT = "колесо — масштаб, перетаскивание — сдвиг, двойной клик — весь щит; клик по аппарату или строке таблицы — карточка";

export const PanelStage = forwardRef<StageHandle, Props>(function PanelStage({ page, panel }, ref) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const pv = useRef<PanelView | null>(null);
  const [zoom, setZoom] = useState("100%");

  useEffect(() => {
    const v = new PanelView(canvas.current!, canvas.current!.parentElement!, panel);
    v.onZoom = setZoom;
    pv.current = v;
    return () => { v.destroy(); pv.current = null; };
  }, [panel]);

  useImperativeHandle(ref, () => ({
    pending: () => 0,
    downloadPng: (f) => downloadSheetPng(page, f),
  }), [page]);

  const major = panel.warnings.filter((w) => w.severity === "major").length;
  const t = panel.totals;
  const kw = (w: number) => (w / 1000).toFixed(2).replace(".", ",");
  return (
    <>
      <canvas ref={canvas} tabIndex={0} aria-label="Щит в лицо" />
      <DeviceCard page={page} panel={panel} />
      <div className="zoom">
        <div className="group">
          <button aria-label="Уменьшить" onClick={() => pv.current?.zoomBy(1 / 1.25)}>−</button>
          <span className="mono" style={{ padding: "0 8px", display: "flex", alignItems: "center" }}>{zoom}</span>
          <button aria-label="Увеличить" onClick={() => pv.current?.zoomBy(1.25)}>+</button>
          <button onClick={() => pv.current?.fit()}>Весь щит</button>
        </div>
        <span className="small muted">
          {`${kw(t.installed)} кВт установлено · ${kw(t.calculated)} кВт / ${t.current} А расчётно · ввод ${panel.input.label}${panel.input.assumed ? "*" : ""}`}
          {major > 0 && ` · слабых мест: ${major}`}
          {` · ${HINT}`}
        </span>
      </div>
    </>
  );
});
