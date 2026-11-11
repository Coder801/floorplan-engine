// Wiring variant on the "Overview" tab (docs/wiring-variants.md, .epd manifest variants): what the
// project holds now, read only. Everything is chosen in the setup wizard (widgets/Wizard); the
// "Change" button opens it. Without the right to choose (an access code) — the same view with no button.
// The code builds all variants: this is only the summary.

import { useTranslation } from "react-i18next";
import type { Variants } from "@/shared/types";
import { activeSummary, breakersOf, optionsOf, parseKey } from "./variants";
import css from "./VariantInfo.module.scss";

interface Props {
  variants: Variants;
  canChoose: boolean;
  onEdit?: () => void;  // the setup wizard; none if there is nothing to ask in the project
}

export function VariantInfo({ variants, canChoose, onEdit }: Props) {
  const { t } = useTranslation();
  const { mode, route } = parseKey(variants.active);
  const current = activeSummary(variants);
  const { path, conduit, plaster, rough_light } = optionsOf(current, mode);
  const rows: [string, string][] = [
    [t("wizard.steps.route.short"), t(`variant.routes.${route}`)],
    [t("wizard.steps.distribution.short"), t(`wizard.steps.distribution.options.${current?.distribution ?? "boxes"}.name`)],
    [t("wizard.steps.path.short"), t(`wizard.steps.path.options.${path}.name`)],
    [t("wizard.steps.conduit.short"), t(`wizard.steps.conduit.options.${conduit}.name`) + (variants.conduit === null ? ` · ${t("variant.typical")}` : "")],
    [t("wizard.steps.plaster.short"), t(`wizard.steps.plaster.options.${plaster}.name`)],
    [t("wizard.steps.rough.short"), t(`wizard.steps.rough.options.${rough_light ? "yes" : "no"}.name`)],
    [t("wizard.steps.breakers.short"), t(`wizard.steps.breakers.options.${breakersOf(mode)}.name`)],
  ];
  return (
    <section className={css.info}>
      <dl className={css.pairs}>
        {rows.map(([k, v]) => [<dt key={`k${k}`}>{k}</dt>, <dd key={`v${k}`}>{v}</dd>])}
      </dl>
      {current && (
        <p className="small muted">
          {t("variant.stats", { devices: current.devices, cable: Math.round(current.cable_m), chases: Math.round(current.chases_m) })}
          {current.edited && <> · {t("variant.edited")}</>}
        </p>
      )}
      <p className="small muted">{canChoose ? t("variant.edits") : t("variant.readOnly")}</p>
      {canChoose && onEdit && <div><button onClick={onEdit}>{t("variant.edit")}</button></div>}
    </section>
  );
}
