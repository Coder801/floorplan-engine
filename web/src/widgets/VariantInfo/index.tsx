// Wiring variant on the "Overview" tab (docs/wiring-variants.md, .epd manifest variants): what the
// project holds now, read only. Everything is chosen in the setup wizard (widgets/Wizard); the
// "Change" button opens it. Without the right to choose (an access code) — the same view with no button.
// The code builds all variants: this is only the summary.

import { useTranslation } from "react-i18next";
import type { Variants } from "@/shared/types";
import { activeSummary, breakersOf, hasLoopDrops, optionsOf, parseKey } from "./variants";
import { Button } from "@/ui/Button";
import { Text } from "@/ui/Text";
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
  const { path, conduit, light_wiring, led_supply, plaster, rough_light, panel_labels, insulation_test, protection_test, loop_conduit } = optionsOf(current, mode);
  const loopDrops = hasLoopDrops({ distribution: current?.distribution ?? "boxes", route, conduit, mode });
  const rows: [string, string][] = [
    [t("wizard.steps.route.short"), t(`variant.routes.${route}`)],
    [t("wizard.steps.distribution.short"), t(`wizard.steps.distribution.options.${current?.distribution ?? "boxes"}.name`)],
    [t("wizard.steps.lights.short"), t(`wizard.steps.lights.options.${light_wiring}.name`)],
    [t("wizard.steps.path.short"), t(`wizard.steps.path.options.${path}.name`)],
    [t("wizard.steps.conduit.short"), t(`wizard.steps.conduit.options.${conduit}.name`) + (variants.conduit === null ? ` · ${t("variant.typical")}` : "")],
    ...(loopDrops ? [[t("wizard.steps.loopConduit.short"), t(`wizard.steps.loopConduit.options.${loop_conduit}.name`)] as [string, string]] : []),
    ...(variants.led ? [[t("wizard.steps.led.short"), t(`wizard.steps.led.options.${led_supply}.name`)] as [string, string]] : []),
    [t("wizard.steps.plaster.short"), t(`wizard.steps.plaster.options.${plaster}.name`)],
    [t("wizard.steps.rough.short"), t(`wizard.steps.rough.options.${rough_light ? "yes" : "no"}.name`)],
    [t("wizard.steps.breakers.short"), t(`wizard.steps.breakers.options.${breakersOf(mode)}.name`)],
    [t("wizard.steps.labels.short"), t(`wizard.steps.labels.options.${panel_labels ? "yes" : "no"}.name`)],
    [t("wizard.steps.insulation.short"), t(`wizard.steps.insulation.options.${insulation_test ? "yes" : "no"}.name`)],
    [t("wizard.steps.protection.short"), t(`wizard.steps.protection.options.${protection_test ? "yes" : "no"}.name`)],
  ];
  return (
    <section className={css.info}>
      <dl className={css.pairs}>
        {rows.map(([k, v]) => [<dt key={`k${k}`}>{k}</dt>, <dd key={`v${k}`}>{v}</dd>])}
      </dl>
      {current && (
        <Text size="small" tone="muted">
          {t("variant.stats", { devices: current.devices, cable: Math.round(current.cable_m), chases: Math.round(current.chases_m) })}
          {current.edited && <> · {t("variant.edited")}</>}
        </Text>
      )}
      <Text size="small" tone="muted">{canChoose ? t("variant.edits") : t("variant.readOnly")}</Text>
      {canChoose && onEdit && <div><Button onClick={onEdit}>{t("variant.edit")}</Button></div>}
    </section>
  );
}
