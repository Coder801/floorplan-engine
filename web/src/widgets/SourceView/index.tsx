// Исходник — на месте чертежа; вкладка листа или «← К листу» возвращает чертёж

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { base, enc, getText } from "@/shared/api";
import { kindOf } from "@/shared/files";
import ui from "@/shared/styles/ui.module.scss";
import type { Project } from "@/shared/types";
import css from "./SourceView.module.scss";

export function SourceView({ project, file, onBack }: { project: Project; file: string; onBack: () => void }) {
  const url = `${base(project.name)}/source/${enc(file)}`;
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
  else body = <div className={ui.empty}>{t("source.noPreview")}</div>;
  return (
    <div className={css.source}>
      <div className={css.bar}>
        <button onClick={onBack}>{t("source.back")}</button>
        <span className={css.name}>{file}</span>
      </div>
      {body}
    </div>
  );
}
