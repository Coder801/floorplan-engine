// What the master switch cuts: quick picks and the groups of the project as rows with a tick.
// A group with a load that must keep working (fridge, boiler, router…) is marked: cutting it is
// allowed, but the person sees what goes dark with it. Used in the setup wizard.

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import ui from "@/shared/styles/ui.module.scss";
import type { OverviewMaster } from "@/shared/types";
import { masterLight, masterPreset, masterRule, toggleMaster, type MasterPreset } from "./master";
import css from "./MasterList.module.scss";

interface Props {
  master: OverviewMaster;
  value: string[];
  onChange: (groups: string[]) => void;
  // "Don't know" as one more quick pick: the person leaves the choice to the studio default
  unknown?: { on: boolean; note: string; onPick: () => void };
}

export function MasterList({ master, value, onChange, unknown }: Props) {
  const { t, i18n } = useTranslation();
  const kw = (w: number) => (w / 1000).toLocaleString(i18n.language, { maximumFractionDigits: 2 });
  // "By hand" stays chosen once pressed, even while the set happens to match a quick pick
  const [hand, setHand] = useState(false);
  const preset: MasterPreset = hand ? "manual" : masterPreset(master, value);
  const picks: { id: MasterPreset; groups: string[] | null }[] = [
    { id: "rule", groups: masterRule(master) },
    { id: "light", groups: masterLight(master) },
    { id: "manual", groups: null },
  ];
  const unsure = unknown?.on === true;
  const choose = (id: MasterPreset, groups: string[] | null) => {
    setHand(id === "manual");
    if (groups) onChange(groups);
  };
  return (
    <>
      <div className={cx(ui.segmented, css.presets)} role="radiogroup" aria-label={t("master.presets.label")}>
        {picks.map(({ id, groups }) => (
          <button key={id} role="radio" aria-checked={!unsure && preset === id} className={cx(!unsure && preset === id && ui.on)}
                  disabled={id !== "manual" && !groups?.length} onClick={() => choose(id, groups ?? (unsure ? value : null))}>
            {t(`master.presets.${id}`)}
          </button>
        ))}
        {unknown && (
          <button role="radio" aria-checked={unsure} className={cx(unsure && ui.on)}
                  onClick={() => { setHand(false); unknown.onPick(); }}>
            {t("wizard.unknown")}
          </button>
        )}
      </div>
      <p className={cx("small muted", css.note)}>{unsure ? unknown.note : t(`master.presets.${preset}Note`)}</p>
      <ul className={css.list}>
        {master.items.map((g) => (
          <li key={g.id}>
            <label className={css.row}>
              <input type="checkbox" checked={value.includes(g.id)}
                     onChange={() => { setHand(true); onChange(toggleMaster(master, value, g.id)); }} />
              <span className="mono">{g.id}</span>
              <span className={css.purpose}>
                {g.purpose}
                {g.keep && <span className={cx("small", css.keep)}> · {t("master.keep")}</span>}
              </span>
              <span className={css.power}>{kw(g.power)} {t("units.kw")}</span>
            </label>
          </li>
        ))}
      </ul>
    </>
  );
}
