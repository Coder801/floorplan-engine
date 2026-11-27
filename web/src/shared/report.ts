// The estimate report for print (GET /api/projects/{key}/result, docs/service-api.md, «Просмотр:
// отчёт для PDF сметы»): an HTML page laid out for A4, or the same page as a PDF download
// (…/result.pdf, printed by the PDF service on the server). The dialog (widgets/ReportDialog) picks the
// parts and the orientation; the page always shows the parts in the fixed order below, so the URL
// lists them in that order too, whatever order they were ticked in. The last choice is remembered
// per browser (report-options), like the theme.
// Excel (…/result.xlsx) is the same estimate as data: only the estimate sections (XLSX_PARTS, no
// plan or panel drawing), no orientation; its choice is remembered apart (report-xlsx-parts).

import { base } from "./api";
import { remember, remembered } from "./palette";

export const REPORT_PARTS = ["plan", "material_rough", "material_finish", "work_rough", "work_finish", "panel"] as const;
export type ReportPart = (typeof REPORT_PARTS)[number];
export const ORIENTATIONS = ["portrait", "landscape"] as const;
export type Orientation = (typeof ORIENTATIONS)[number];

export const XLSX_PARTS = ["material_rough", "material_finish", "work_rough", "work_finish"] as const satisfies readonly ReportPart[];
export type XlsxPart = (typeof XLSX_PARTS)[number];

export interface ReportOptions { parts: ReportPart[]; orientation: Orientation }

export const DEFAULT_REPORT: ReportOptions = { parts: [...REPORT_PARTS], orientation: "portrait" };

export function reportUrl(
  key: string, parts: Iterable<ReportPart>, orientation: Orientation, pdf = false,
): string {
  const on = new Set(parts);
  const list = REPORT_PARTS.filter((p) => on.has(p)).join(",");
  return `${base(key)}/result${pdf ? ".pdf" : ""}?parts=${list}&orientation=${orientation}`;
}

export function xlsxUrl(key: string, parts: Iterable<ReportPart>): string {
  const on = new Set(parts);
  return `${base(key)}/result.xlsx?parts=${XLSX_PARTS.filter((p) => on.has(p)).join(",")}`;
}

// The PDF as a file download: the name from the server ("<project> — <document>.pdf"); a refusal
// (no PDF service — 503, it failed — 502) is an Error with the server's message
export function downloadReportPdf(
  key: string, parts: Iterable<ReportPart>, orientation: Orientation,
): Promise<void> {
  return download(reportUrl(key, parts, orientation, true), "report.pdf");
}

// The Excel of the chosen estimate sections, the same way
export function downloadReportXlsx(key: string, parts: Iterable<ReportPart>): Promise<void> {
  return download(xlsxUrl(key, parts), "estimate.xlsx");
}

async function download(url: string, fallback: string): Promise<void> {
  const r = await fetch(url);
  if (!r.ok) {
    let message = r.statusText;
    try { message = (await r.json()).detail ?? message; } catch { /* not JSON */ }
    throw new Error(message || String(r.status));
  }
  const blob = await r.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = pdfName(r.headers.get("Content-Disposition"), fallback);
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), 60_000);
}

// filename*=UTF-8''… (the real name) wins over the plain filename="…"; none — the fallback
export function pdfName(disposition: string | null, fallback = "report.pdf"): string {
  const utf = disposition?.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf) {
    try { return decodeURIComponent(utf[1]); } catch { /* broken escape: fall through */ }
  }
  return disposition?.match(/filename="([^"]+)"/i)?.[1] ?? fallback;
}

const KEY = "report-options";

// Stored choice, cleaned: unknown parts dropped, nothing ticked or a broken value is the default
export function savedReport(): ReportOptions {
  try {
    const v = JSON.parse(remembered(KEY) || "null") as Partial<ReportOptions> | null;
    const parts = REPORT_PARTS.filter((p) => Array.isArray(v?.parts) && v.parts.includes(p));
    const orientation = ORIENTATIONS.find((o) => o === v?.orientation) ?? DEFAULT_REPORT.orientation;
    return parts.length ? { parts, orientation } : { ...DEFAULT_REPORT, orientation };
  } catch {
    return DEFAULT_REPORT;
  }
}

export function rememberReport(options: ReportOptions) {
  remember(KEY, JSON.stringify(options));
}

const XLSX_KEY = "report-xlsx-parts";

// Stored Excel sections, cleaned like savedReport; nothing ticked or broken — all of them
export function savedXlsx(): XlsxPart[] {
  try {
    const v = JSON.parse(remembered(XLSX_KEY) || "null") as unknown;
    const parts = XLSX_PARTS.filter((p) => Array.isArray(v) && v.includes(p));
    return parts.length ? parts : [...XLSX_PARTS];
  } catch {
    return [...XLSX_PARTS];
  }
}

export function rememberXlsx(parts: Iterable<ReportPart>) {
  const on = new Set(parts);
  remember(XLSX_KEY, JSON.stringify(XLSX_PARTS.filter((p) => on.has(p))));
}
