// What the master switch cuts: quick picks and the groups of the project as rows with a tick.
// A group with a load that must keep working (fridge, boiler, router…) is marked: cutting it is
// allowed, but the person sees what goes dark with it. Used in the setup wizard.

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import { Checkbox } from "@/ui/Checkbox";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { Text } from "@/ui/Text";
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
      <SegmentedControl<MasterPreset | "unknown"> className={css.presets} label={t("master.presets.label")}
        value={unsure ? "unknown" : preset}
        onChange={(id) => {
          if (id === "unknown") { setHand(false); unknown?.onPick(); return; }
          const pick = picks.find((p) => p.id === id);
          choose(id, pick?.groups ?? (unsure ? value : null));
        }}
        options={[
          ...picks.map(({ id, groups }) => ({ value: id, label: t(`master.presets.${id}`), disabled: id !== "manual" && !groups?.length })),
          ...(unknown ? [{ value: "unknown" as const, label: t("wizard.unknown") }] : []),
        ]} />
      <Text size="small" tone="muted" className={css.note}>{unsure ? unknown.note : t(`master.presets.${preset}Note`)}</Text>
      <ul className={css.list}>
        {master.items.map((g) => (
          <li key={g.id}>
            <Checkbox className={css.row} checked={value.includes(g.id)}
                      onChange={() => { setHand(true); onChange(toggleMaster(master, value, g.id)); }}
                      label={<span className={css.cols}>
                        <span className="mono">{g.id}</span>
                        <span className={css.purpose}>
                          {g.purpose}
                          {g.keep && <span className={cx("small", css.keep)}> · {t("master.keep")}</span>}
                        </span>
                        <span className={css.power}>{kw(g.power)} {t("units.kw")}</span>
                      </span>} />
          </li>
        ))}
      </ul>
    </>
  );
}
