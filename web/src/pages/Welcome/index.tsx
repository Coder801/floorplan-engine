// Welcome screen: project choice as cards (ProjectCard) over the whole page, until a project
// is open.

import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { ProjectSummary } from "@/shared/types";
import { BRAND, STAGE } from "@/shared/version";
import { Heading } from "@/ui/Heading";
import { Logo } from "@/ui/Logo";
import { Text } from "@/ui/Text";
import { ProjectCard } from "@/widgets/ProjectCard";
import css from "./Welcome.module.scss";

// settings — the gear from the header (the welcome screen covers it): theme, language, studio
export function Welcome({ list, onOpen, settings }: { list: ProjectSummary[]; onOpen: (name: string) => void; settings?: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className={css.welcome} role="dialog" aria-modal="true" aria-labelledby="welcome-title">
      <div className={css.inner}>
        <div className={css.head}>
          <Logo size={56} />
          <div>
            <Heading level={1} size="display" id="welcome-title" className={css.brand}>{BRAND} <span className={css.stage}>{t(`app.stages.${STAGE}`)}</span></Heading>
            <Text size="lead" tone="muted">{t("welcome.tagline")}</Text>
          </div>
          {/* Its own cell: the gear's grid-area is the header's */}
          {settings && <div className={css.settings}>{settings}</div>}
        </div>
        <Text size="lead" tone="muted" align="center" className={css.lead}>{t("welcome.lead")}</Text>
        {!list.length && (
          <div className={css.none}>
            <div>{t("welcome.empty")}</div>
            <code className="mono">{`uv run floorplan-engine build projects/<${t("welcome.placeholder")}>`}</code>
          </div>
        )}
        <div className={css.grid}>
          {list.map((p) => (
            <ProjectCard key={p.id} p={p} onOpen={onOpen} />
          ))}
        </div>
      </div>
    </div>
  );
}
