// Project menu: slides in from the left on the "›" button in the header, with cards as on the
// start screen (Welcome.ProjectCard). Closed by the button, Esc, a click outside or picking a project.

import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { isProject } from "@/shared/api";
import { REDUCED_MOTION } from "@/shared/consts";
import { cx } from "@/shared/cx";
import type { ProjectSummary } from "@/shared/types";
import { IconButton } from "@/ui/IconButton";
import { PanelHeader } from "@/ui/PanelHeader";
import { Text } from "@/ui/Text";
import { ProjectCard } from "@/widgets/ProjectCard";
import css from "./ProjectsMenu.module.scss";

interface Props {
  list: ProjectSummary[];
  current: string | null;
  closing: boolean;                 // asked to close: the menu slides out to the left
  onOpen: (name: string) => void;
  onClose: () => void;              // start sliding out
  onClosed: () => void;             // slid out: remove
}

export function ProjectsMenu({ list, current, closing, onOpen, onClose, onClosed }: Props) {
  const { t } = useTranslation();
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => { if (ev.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  // Without animation there is no animation end, so remove right away
  useEffect(() => { if (closing && REDUCED_MOTION) onClosed(); }, [closing, onClosed]);

  return (
    <>
      <div className={cx(css.backdrop, closing && css.out)} onClick={onClose} aria-hidden="true" />
      <nav className={cx(css.menu, closing && css.out)} aria-label={t("projects.title")}
           onAnimationEnd={(ev) => { if (closing && ev.target === ev.currentTarget) onClosed(); }}>
        <PanelHeader title={t("projects.title")}>
          <IconButton label={t("common.close")} title={t("common.closeEsc")} onClick={onClose}>←</IconButton>
        </PanelHeader>
        <div className={css.list}>
          {!list.length && <Text size="small" tone="muted">{t("projects.empty")}</Text>}
          {list.map((p) => (
            <ProjectCard key={p.id} p={p} current={isProject(p, current)} onOpen={onOpen} />
          ))}
        </div>
      </nav>
    </>
  );
}
