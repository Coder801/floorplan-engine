// "Download" at the end of the drawing options: sheet PNG for the album or the DXF of the whole
// project (engineering interface mode only)

import { useTranslation } from "react-i18next";
import { usePopover } from "@/shared/popover";
import { Button } from "@/ui/Button";
import { Menu } from "@/ui/Menu";
import { MenuItem } from "@/ui/MenuItem";
import { Tag } from "@/ui/Tag";
import css from "./DownloadMenu.module.scss";

interface Props {
  onPng: (() => void) | null;   // missing means no sheet is open (a source, loading)
  dxf: { href: string; name: string } | null;
  withDxf?: boolean;            // the simple interface mode offers only the sheet PNG
}

export function DownloadMenu({ onPng, dxf, withDxf = true }: Props) {
  const { open, closing, setOpen, toggle, ref } = usePopover<HTMLDivElement>();
  const { t } = useTranslation();
  return (
    <div ref={ref} className={css.download}>
      <Button className={css.button} aria-label={t("download.download")} aria-haspopup="menu" aria-expanded={open} onClick={toggle}
              icon={<DownloadIcon />}>
        <span className={css.label}>{t("download.download")}</span> <span aria-hidden="true">▾</span>
      </Button>
      {open && (
        <Menu closing={closing} minWidth={300}>
          <MenuItem icon={<Tag variant="mono">PNG</Tag>} note="A3, 150 dpi" disabled={!onPng}
                    onClick={() => { onPng?.(); setOpen(false); }}>{t("download.sheet")}</MenuItem>
          {!withDxf ? null : dxf ? (
            <MenuItem icon={<Tag variant="mono">DXF</Tag>} note={t("download.allSheets")} href={dxf.href} download={dxf.name}
                      onClick={() => setOpen(false)}>{t("download.dxf")}</MenuItem>
          ) : (
            <MenuItem icon={<Tag variant="mono">DXF</Tag>} disabled>{t("download.notBuilt")}</MenuItem>
          )}
        </Menu>
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
