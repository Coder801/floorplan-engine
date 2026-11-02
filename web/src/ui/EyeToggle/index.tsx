// Видимость слоя — глаз, как в слоях Photoshop: открытый — слой виден, перечёркнутый — скрыт.
// Кнопка с aria-pressed (нажата — виден); подпись — что показать или скрыть.

import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import css from "./EyeToggle.module.scss";

interface Props {
  on: boolean;            // слой виден
  onToggle: () => void;
  what: string;           // что скрывает и показывает — для подсказки и экранного диктора
  className?: string;
}

export function EyeToggle({ on, onToggle, what, className }: Props) {
  const { t } = useTranslation();
  const label = t(on ? "eye.hide" : "eye.show", { what });
  return (
    <button type="button" className={cx(css.eye, !on && css.off, className)} aria-pressed={on}
            aria-label={label} title={label}
            onClick={(e) => { e.stopPropagation(); onToggle(); }}>
      <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
        <path d="M2 12s3.6-6.5 10-6.5S22 12 22 12s-3.6 6.5-10 6.5S2 12 2 12Z" />
        <circle cx="12" cy="12" r="3" />
        {!on && <path d="M4 20 20 4" />}
      </svg>
    </button>
  );
}
