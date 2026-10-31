// Меню проектов: выезжает слева по кнопке «›» в шапке — карточки, как на входном экране
// (Welcome.ProjectCard). Закрывается кнопкой, Esc, кликом мимо или выбором проекта.

import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { REDUCED_MOTION } from "@/shared/consts";
import { cx } from "@/shared/cx";
import ui from "@/shared/styles/ui.module.scss";
import type { ProjectSummary } from "@/shared/types";
import { ProjectCard } from "@/widgets/ProjectCard";
import css from "./ProjectsMenu.module.scss";

interface Props {
  list: ProjectSummary[];
  current: string | null;
  closing: boolean;                 // попросили закрыть — меню уезжает влево
  onOpen: (name: string) => void;
  onClose: () => void;              // запустить уезжание
  onClosed: () => void;             // уехало — убрать
}

export function ProjectsMenu({ list, current, closing, onOpen, onClose, onClosed }: Props) {
  const { t } = useTranslation();
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => { if (ev.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  // Без анимации конца анимации не будет — убрать сразу
  useEffect(() => { if (closing && REDUCED_MOTION) onClosed(); }, [closing, onClosed]);

  return (
    <>
      <div className={cx(css.backdrop, closing && css.out)} onClick={onClose} aria-hidden="true" />
      <nav className={cx(css.menu, closing && css.out)} aria-label={t("projects.title")}
           onAnimationEnd={(ev) => { if (closing && ev.target === ev.currentTarget) onClosed(); }}>
        <div className={cx(ui.panelHead, css.head)}>
          <h2>{t("projects.title")}</h2>
          <button aria-label={t("common.close")} title={t("common.closeEsc")} onClick={onClose}>←</button>
        </div>
        <div className={css.list}>
          {!list.length && <p className="muted small">{t("projects.empty")}</p>}
          {list.map((p) => (
            <ProjectCard key={p.name} p={p} current={p.name === current} onOpen={onOpen} />
          ))}
        </div>
      </nav>
    </>
  );
}
