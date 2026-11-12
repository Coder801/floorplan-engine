// The source replaces the drawing; the sheet tab or "← Back to sheet" brings the drawing back

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { base, enc, getText } from "@/shared/api";
import { kindOf } from "@/shared/files";
import type { Project } from "@/shared/types";
import { Button } from "@/ui/Button";
import { EmptyState } from "@/ui/EmptyState";
import css from "./SourceView.module.scss";

export function SourceView({ project, file, onBack }: { project: Project; file: string; onBack: () => void }) {
  const url = `${base(project.id)}/source/${enc(file)}`;
  const kind = kindOf(file);
  const { t } = useTranslation();
  const [text, setText] = useState("…");
  useEffect(() => {
    if (kind !== "text") return;
    let alive = true;
    getText(url).then((s) => alive && setText(s), (e) => alive && setText((e as Error).message));
    return () => { alive = false; };
  }, [url, kind]);
  let body: React.ReactNode;
  if (kind === "pdf") body = <iframe className={css.frame} src={url} title={file} />;
  else if (kind === "image") body = <img className={css.img} src={url} alt={file} />;
  else if (kind === "text") body = <pre className={css.text}>{text}</pre>;
  else body = <EmptyState>{t("source.noPreview")}</EmptyState>;
  return (
    <div className={css.source}>
      <div className={css.bar}>
        <Button size="sm" onClick={onBack}>{t("source.back")}</Button>
        <span className={css.name}>{file}</span>
      </div>
      {body}
    </div>
  );
}
