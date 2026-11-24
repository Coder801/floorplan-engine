// "Download" at the end of the drawing options: sheet PNG for the album, the DXF of the whole
// project (engineering interface mode only) and the estimate for print (both modes, while the
// electrical service is on): the last one opens ReportDialog instead of a download. The sheet PNG
// and the DXF are paused for now (FILES_PAUSED): the items stay in the menu, off, with a note

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { usePopover } from "@/shared/popover";
import { Button } from "@/ui/Button";
import { Menu } from "@/ui/Menu";
import { MenuItem } from "@/ui/MenuItem";
import { Tag } from "@/ui/Tag";
import { ReportDialog } from "@/widgets/ReportDialog";
import css from "./DownloadMenu.module.scss";

// Sheet PNG and project DXF downloads are off for now (2026-11-24); false brings them back
export const FILES_PAUSED = true;

interface Props {
  onPng: (() => void) | null;   // missing means no sheet is open (a source, loading)
  dxf: { href: string; name: string } | null;
  withDxf?: boolean;            // the simple interface mode offers no DXF
  // Project key for the estimate for print; null: the project is not built; missing: no such item
  // (the electrical service is off)
  report?: string | null;
}

export function DownloadMenu({ onPng, dxf, withDxf = true, report }: Props) {
  const { open, closing, setOpen, toggle, ref } = usePopover<HTMLDivElement>();
  const [reportOpen, setReportOpen] = useState(false);
  const { t } = useTranslation();
  return (
    <div ref={ref} className={css.download}>
      <Button className={css.button} aria-label={t("download.download")} aria-haspopup="menu" aria-expanded={open} onClick={toggle}
              icon={<DownloadIcon />}>
        <span className={css.label}>{t("download.download")}</span> <span aria-hidden="true">▾</span>
      </Button>
      {open && (
        <Menu closing={closing} minWidth={300}>
          <MenuItem icon={<Tag variant="mono">PNG</Tag>} note={FILES_PAUSED ? t("download.paused") : "A3, 150 dpi"}
                    disabled={FILES_PAUSED || !onPng}
                    onClick={() => { onPng?.(); setOpen(false); }}>{t("download.sheet")}</MenuItem>
          {!withDxf ? null : FILES_PAUSED ? (
            <MenuItem icon={<Tag variant="mono">DXF</Tag>} note={t("download.paused")} disabled>{t("download.dxf")}</MenuItem>
          ) : dxf ? (
            <MenuItem icon={<Tag variant="mono">DXF</Tag>} note={t("download.allSheets")} href={dxf.href} download={dxf.name}
                      onClick={() => setOpen(false)}>{t("download.dxf")}</MenuItem>
          ) : (
            <MenuItem icon={<Tag variant="mono">DXF</Tag>} disabled>{t("download.notBuilt")}</MenuItem>
          )}
          {report !== undefined && (
            <MenuItem icon={<Tag variant="mono">A4</Tag>} note={report ? "HTML" : t("download.notBuilt")} disabled={!report}
                      onClick={() => { setOpen(false); setReportOpen(true); }}>{t("download.report")}</MenuItem>
          )}
        </Menu>
      )}
      {reportOpen && report && <ReportDialog projectKey={report} onClose={() => setReportOpen(false)} />}
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
