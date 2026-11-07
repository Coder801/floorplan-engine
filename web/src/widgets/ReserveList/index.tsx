// What stays on the backup bus: the groups of the project with their power and the sum against
// the power of the source. Used on the "Panel" page (ReserveStage) and in the setup wizard. A
// sum near or over the limit only warns, with a sign and a word: not everything runs at once,
// and the source may be larger.

import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import type { OverviewReserve } from "@/shared/types";
import { reserveLevel, reservePower, toggleGroup } from "./reserve";
import css from "./ReserveList.module.scss";

interface Props {
  reserve: OverviewReserve;
  value: string[];
  disabled?: boolean;
  onChange: (groups: string[]) => void;
}

export function ReserveList({ reserve, value, disabled = false, onChange }: Props) {
  const { t, i18n } = useTranslation();
  const kw = (w: number) => (w / 1000).toLocaleString(i18n.language, { maximumFractionDigits: 2 });
  const power = reservePower(reserve, value);
  const limit = reserve.limit_kw;
  const level = reserveLevel(power, limit);
  return (
    <>
      <p className={cx(css.sum, level !== "ok" && css[level])} aria-live="polite">
        {level !== "ok" && <Sign level={level} />}
        <span>
          {limit === null
            ? t("reserve.sumNoLimit", { power: kw(power) })
            : t("reserve.sum", { power: kw(power), limit: kw(limit * 1000) })}
          {reserve.limit_assumed && <span className="muted"> · {t("reserve.assumed")}</span>}
          {level !== "ok" && <span> · {t(`reserve.${level}`)}</span>}
        </span>
      </p>
      <ul className={css.list}>
        {reserve.items.map((g) => (
          <li key={g.id}>
            <label className={css.row}>
              <input type="checkbox" checked={value.includes(g.id)} disabled={disabled}
                     onChange={() => onChange(toggleGroup(reserve, value, g.id))} />
              <span className="mono">{g.id}</span>
              <span className={css.purpose}>{g.purpose}</span>
              <span className={css.power}>{kw(g.power)} {t("units.kw")}</span>
            </label>
          </li>
        ))}
      </ul>
    </>
  );
}

// A triangle: over the limit a red one with a lightning bolt, near it a yellow one with "!"
function Sign({ level }: { level: "near" | "over" }) {
  return (
    <svg className={css.sign} viewBox="0 0 24 24" aria-hidden="true">
      <path className={css.triangle} d="M12 2.500 23 21.500H1z" />
      {level === "over"
        ? <path className={css.mark} d="M13.500 8.500 8.500 15h3l-1 4.500 5-6.500h-3z" />
        : <path className={css.mark} d="M10.800 9h2.400l-.5 6.500h-1.400zM12 16.300a1.300 1.300 0 1 0 0 2.600 1.300 1.300 0 0 0 0-2.600z" />}
    </svg>
  );
}
