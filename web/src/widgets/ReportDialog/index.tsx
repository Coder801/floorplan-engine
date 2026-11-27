// "Estimate for print" (the Download menu): which parts of the electrical estimate the report
// shows and the page orientation, then "Download PDF" saves the report as a PDF file (printed on
// the server; the dialog waits and shows a refusal) or "Open" puts the HTML report in a new tab
// (shared/report.ts). Esc, the veil and "Cancel" close it; the last choice is remembered in the
// browser. format "xlsx" ("Download Excel" on the Estimate tab): the same dialog for the estimate as
// Excel — only the estimate sections (data, no drawings), no orientation and no "Open".

import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ORIENTATIONS, REPORT_PARTS, XLSX_PARTS, downloadReportPdf, downloadReportXlsx, rememberReport, rememberXlsx, reportUrl,
  savedReport, savedXlsx, type Orientation, type ReportPart,
} from "@/shared/report";
import { Button } from "@/ui/Button";
import { Checkbox } from "@/ui/Checkbox";
import { Heading } from "@/ui/Heading";
import { Modal } from "@/ui/Modal";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { Stack } from "@/ui/Stack";
import { Text } from "@/ui/Text";
import css from "./ReportDialog.module.scss";

interface Props {
  projectKey: string;
  onClose: () => void;
  format?: "pdf" | "xlsx";
}

export function ReportDialog({ projectKey, onClose, format = "pdf" }: Props) {
  const { t } = useTranslation();
  const xlsx = format === "xlsx";
  const [saved] = useState(savedReport);
  const [parts, setParts] = useState<Set<ReportPart>>(() => new Set(xlsx ? savedXlsx() : saved.parts));
  const shown: readonly ReportPart[] = xlsx ? XLSX_PARTS : REPORT_PARTS;
  const [orientation, setOrientation] = useState<Orientation>(saved.orientation);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const title = useId();
  const lead = useId();
  const group = useId();

  const toggle = (p: ReportPart, on: boolean) => setParts((s) => {
    const next = new Set(s);
    if (on) next.add(p); else next.delete(p);
    return next;
  });
  const remember = () => (xlsx ? rememberXlsx(parts)
    : rememberReport({ parts: REPORT_PARTS.filter((p) => parts.has(p)), orientation }));
  // "Download PDF" is the form's submit (Enter): the PDF takes a few seconds, the dialog waits
  const submit = async (ev: React.FormEvent) => {
    ev.preventDefault();
    if (!parts.size || busy) return;
    setBusy(true);
    setError(null);
    try {
      await (xlsx ? downloadReportXlsx(projectKey, parts) : downloadReportPdf(projectKey, parts, orientation));
      remember();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };
  const open = () => {
    if (!parts.size) return;
    window.open(reportUrl(projectKey, parts, orientation), "_blank", "noopener");
    remember();
    onClose();
  };
  return (
    <Modal as="form" size="sm" onClose={onClose} onSubmit={submit} labelledBy={title} describedBy={lead}>
      <Heading level={2} id={title}>{t(xlsx ? "report.xlsxTitle" : "report.title")}</Heading>
      <Text id={lead} tone="muted">{t(xlsx ? "report.xlsxLead" : "report.lead")}</Text>
      <Stack gap={2} role="group" aria-labelledby={group}>
        <Heading level={3} size="caps" id={group}>{t("report.electrical")}</Heading>
        {shown.map((p) => (
          <Checkbox key={p} checked={parts.has(p)} onChange={(on) => toggle(p, on)} label={t(`report.part.${p}`)} />
        ))}
      </Stack>
      {!xlsx && (
        <Stack gap={2}>
          <Heading level={3} size="caps">{t("report.orientation")}</Heading>
          <SegmentedControl fill label={t("report.orientation")} value={orientation} onChange={setOrientation}
                            options={ORIENTATIONS.map((o) => ({ value: o, label: t(`report.${o}`) }))} />
        </Stack>
      )}
      {!parts.size && <Text size="small" tone="muted">{t("report.nothing")}</Text>}
      {error && <Text size="small" tone="critical" role="alert">{t(xlsx ? "report.xlsxFailed" : "report.pdfFailed", { error })}</Text>}
      <Button type="submit" variant="primary" block className={css.pdf} disabled={!parts.size || busy}>
        {xlsx ? (busy ? t("report.xlsxBusy") : t("report.xlsx")) : (busy ? t("report.pdfBusy") : t("report.pdf"))}
      </Button>
      <Stack direction="row" gap={2} wrap={false} className={css.buttons}>
        {!xlsx && <Button onClick={open} disabled={!parts.size || busy}>{t("report.open")}</Button>}
        <Button onClick={onClose}>{t("report.cancel")}</Button>
      </Stack>
    </Modal>
  );
}
