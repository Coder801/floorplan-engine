// Шкала масштаба справа у чертежа (вертикальная): «+» сверху, пять позиций шагов (zoom.ts) —
// клик по позиции или перетаскивание ползунка, «−» снизу, «вписать» под ней; без процентов
// (шаг — в aria-valuetext и подсказке деления). Переход на шаг плавный (Glide в холсте).

import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { LAST_STEP, ZOOM_STEPS, zoomLabel, type Zoom } from "@/shared/zoom";
import css from "./ZoomRail.module.scss";

interface Props {
  zoom: Zoom;
  onStep: (step: number) => void;  // шаг, на который перейти (за крайние холст не пустит)
  onFit: () => void;
  fitLabel: string;
  free?: { onZoom: (dir: -1 | 1) => void };  // масштаб без шагов (3D): без шкалы
}

// Позиция шага на шкале снизу вверх, доля высоты
const at = (step: number) => step / LAST_STEP;

export function ZoomRail({ zoom, onStep, onFit, fitLabel, free }: Props) {
  const { t } = useTranslation();
  const track = useRef<HTMLDivElement>(null);
  // Ближайший шаг к точке на шкале
  const stepAt = (clientY: number) => {
    const r = track.current!.getBoundingClientRect();
    return Math.round((1 - (clientY - r.top) / r.height) * LAST_STEP);
  };
  const plus = free ? () => free.onZoom(1) : () => onStep(zoom.step + 1);
  const minus = free ? () => free.onZoom(-1) : () => onStep(zoom.step - 1);
  return (
    <div className={css.rail} role="group" aria-label={t("zoom.label")}>
      <button aria-label={t("zoom.in")} disabled={!free && zoom.step >= LAST_STEP} onClick={plus}>+</button>
      {!free && (
        <div ref={track} className={css.track} role="slider" tabIndex={0} aria-orientation="vertical"
             aria-valuemin={0} aria-valuemax={LAST_STEP} aria-valuenow={zoom.step} aria-valuetext={zoom.label}
             onPointerDown={(e) => { e.currentTarget.setPointerCapture(e.pointerId); onStep(stepAt(e.clientY)); }}
             onPointerMove={(e) => { if (e.buttons & 1) onStep(stepAt(e.clientY)); }}
             onKeyDown={(e) => {
               if (e.key === "ArrowUp" || e.key === "ArrowRight") { e.preventDefault(); onStep(zoom.step + 1); }
               if (e.key === "ArrowDown" || e.key === "ArrowLeft") { e.preventDefault(); onStep(zoom.step - 1); }
               if (e.key === "Home") onStep(0);
               if (e.key === "End") onStep(LAST_STEP);
             }}>
          <span className={css.line} aria-hidden="true" />
          {ZOOM_STEPS.map((_, k) => (
            <span key={k} className={cx(css.stop, k <= zoom.step && css.passed)} style={{ bottom: `${at(k) * 100}%` }}
                  title={zoomLabel(k)} aria-hidden="true" />
          ))}
          <span className={css.thumb} style={{ bottom: `${at(zoom.step) * 100}%` }} aria-hidden="true" />
        </div>
      )}
      <button aria-label={t("zoom.out")} disabled={!free && zoom.step <= 0} onClick={minus}>−</button>
      <button className={css.fit} aria-label={fitLabel} title={fitLabel} onClick={onFit}>
        <FitIcon />
      </button>
    </div>
  );
}

function FitIcon() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="none" stroke="currentColor"
         strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 6V2h4M10 2h4v4M14 10v4h-4M6 14H2v-4" />
    </svg>
  );
}
