// Меню проектов: выезжает слева по кнопке «›» в шапке — карточки, как на входном экране
// (Welcome.ProjectCard). Закрывается кнопкой, Esc, кликом мимо или выбором проекта.

import { useEffect } from "react";
import { REDUCED_MOTION } from "./consts";
import { cx } from "./cx";
import css from "./ProjectsMenu.module.scss";
import ui from "./styles/ui.module.scss";
import type { ProjectSummary } from "./types";
import { ProjectCard } from "./Welcome";

interface Props {
  list: ProjectSummary[];
  current: string | null;
  closing: boolean;                 // попросили закрыть — меню уезжает влево
  onOpen: (name: string) => void;
  onClose: () => void;              // запустить уезжание
  onClosed: () => void;             // уехало — убрать
}

export function ProjectsMenu({ list, current, closing, onOpen, onClose, onClosed }: Props) {
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
      <nav className={cx(css.menu, closing && css.out)} aria-label="Проекты"
           onAnimationEnd={(ev) => { if (closing && ev.target === ev.currentTarget) onClosed(); }}>
        <div className={cx(ui.panelHead, css.head)}>
          <h2>Проекты</h2>
          <button aria-label="Закрыть" title="Закрыть (Esc)" onClick={onClose}>←</button>
        </div>
        <div className={css.list}>
          {!list.length && <p className="muted small">Нет собранных проектов.</p>}
          {list.map((p) => (
            <ProjectCard key={p.name} p={p} current={p.name === current} onOpen={onOpen} />
          ))}
        </div>
      </nav>
    </>
  );
}
