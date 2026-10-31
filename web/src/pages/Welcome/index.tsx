// Экран приветствия: выбор проекта карточками (ProjectCard) на всю страницу, пока проект
// не открыт.

import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import type { ProjectSummary } from "@/shared/types";
import { Logo } from "@/ui/Logo";
import { ProjectCard } from "@/widgets/ProjectCard";
import css from "./Welcome.module.scss";

export function Welcome({ list, onOpen }: { list: ProjectSummary[]; onOpen: (name: string) => void }) {
  const { t } = useTranslation();
  return (
    <div className={css.welcome} role="dialog" aria-modal="true" aria-labelledby="welcome-title">
      <div className={css.inner}>
        <div className={css.head}>
          <Logo size={56} />
          <div>
            <h1 id="welcome-title" className={css.brand}>Shtroba</h1>
            <p className="muted">{t("welcome.tagline")}</p>
          </div>
        </div>
        <p className={cx(css.lead, "muted")}>{t("welcome.lead")}</p>
        {!list.length && (
          <div className={css.none}>
            <div>{t("welcome.empty")}</div>
            <code className="mono">{`uv run floorplan-engine build projects/<${t("welcome.placeholder")}>`}</code>
          </div>
        )}
        <div className={css.grid}>
          {list.map((p) => (
            <ProjectCard key={p.name} p={p} onOpen={onOpen} />
          ))}
        </div>
      </div>
    </div>
  );
}
