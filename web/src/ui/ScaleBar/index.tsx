// Scale bar at the bottom right of the drawing: a round length (zoom.rulerLength) in object mm
// (model, panel or wall) at the current zoom

import { useTranslation } from "react-i18next";
import { rulerLength, type Zoom } from "@/shared/zoom";
import css from "./ScaleBar.module.scss";

export function ScaleBar({ zoom }: { zoom: Zoom }) {
  const { t } = useTranslation();
  if (!zoom.pxPerMm) return null;
  const r = rulerLength(zoom.pxPerMm);
  return (
    <div className={css.ruler} aria-label={t("zoom.ruler", { length: r.label })}>
      <span className={css.bar} style={{ width: `${r.px}px` }} aria-hidden="true">
        <i /><i /><i /><i /><i />
      </span>
      <span className="mono">{r.label}</span>
    </div>
  );
}
