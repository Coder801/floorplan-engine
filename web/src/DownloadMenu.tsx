// «Скачать» в правом верхнем углу чертежа: PNG листа для альбома или DXF всего проекта

import css from "./DownloadMenu.module.scss";
import { usePopover } from "./popover";
import menu from "./styles/menu.module.scss";

interface Props {
  onPng: (() => void) | null;   // нет — лист не открыт (исходник, загрузка)
  dxf: { href: string; name: string } | null;
}

export function DownloadMenu({ onPng, dxf }: Props) {
  const { open, setOpen, toggle, ref } = usePopover<HTMLDivElement>();
  return (
    <div ref={ref} className={css.download}>
      <button className={css.button} aria-label="Скачать" aria-haspopup="menu" aria-expanded={open} onClick={toggle}>
        <DownloadIcon /> <span className={css.label}>Скачать</span> <span aria-hidden="true">▾</span>
      </button>
      {open && (
        <div className={menu.panel} role="menu">
          <button className={menu.item} role="menuitem" disabled={!onPng}
                  onClick={() => { onPng?.(); setOpen(false); }}>
            <span className={css.badge}>PNG</span>
            Лист для альбома
            <span className={menu.note}>A3, 150 dpi</span>
          </button>
          {dxf ? (
            <a className={menu.item} role="menuitem" href={dxf.href} download={dxf.name} onClick={() => setOpen(false)}>
              <span className={css.badge}>DXF</span>
              Проект для AutoCAD
              <span className={menu.note}>все листы</span>
            </a>
          ) : (
            <button className={menu.item} role="menuitem" disabled>
              <span className={css.badge}>DXF</span>
              Проект не собран
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function DownloadIcon() {
  return (
    <svg className={css.icon} viewBox="0 0 16 16" aria-hidden="true">
      <path d="M8 2v8M4.5 6.5 8 10l3.5-3.5M3 13h10" />
    </svg>
  );
}
