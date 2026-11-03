// Vertical zoom scale on the right of the drawing: "+" on top, five step positions (zoom.ts),
// click a position or drag the slider, "−" at the bottom, "fit" below it; no percentages (the
// step is in aria-valuetext and the division tooltip). Moving to a step is smooth (Glide in the canvas).

import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { LAST_STEP, ZOOM_STEPS, zoomLabel, type Zoom } from "@/shared/zoom";
import css from "./ZoomRail.module.scss";

interface Props {
  zoom: Zoom;
  onStep: (step: number) => void;  // the step to go to (the canvas will not go past the ends)
  onFit: () => void;
  fitLabel: string;
}

// Step position on the scale from bottom to top, as a fraction of the height
const at = (step: number) => step / LAST_STEP;

export function ZoomRail({ zoom, onStep, onFit, fitLabel }: Props) {
  const { t } = useTranslation();
  const track = useRef<HTMLDivElement>(null);
  // The step nearest to a point on the scale
  const stepAt = (clientY: number) => {
    const r = track.current!.getBoundingClientRect();
    return Math.round((1 - (clientY - r.top) / r.height) * LAST_STEP);
  };
  return (
    <div className={css.rail} role="group" aria-label={t("zoom.label")}>
      <button aria-label={t("zoom.in")} disabled={zoom.step >= LAST_STEP} onClick={() => onStep(zoom.step + 1)}>+</button>
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
      <button aria-label={t("zoom.out")} disabled={zoom.step <= 0} onClick={() => onStep(zoom.step - 1)}>−</button>
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
