// Исходник — на месте чертежа; вкладка листа или «← К листу» возвращает чертёж

import { useEffect, useState } from "react";
import { base, enc, getText } from "./api";
import { kindOf } from "./Drawer";
import css from "./SourceView.module.scss";
import ui from "./styles/ui.module.scss";
import type { Project } from "./types";

export function SourceView({ project, file, onBack }: { project: Project; file: string; onBack: () => void }) {
  const url = `${base(project.name)}/source/${enc(file)}`;
  const kind = kindOf(file);
  const [text, setText] = useState("…");
  useEffect(() => {
    if (kind !== "text") return;
    let alive = true;
    getText(url).then((t) => alive && setText(t), (e) => alive && setText((e as Error).message));
    return () => { alive = false; };
  }, [url, kind]);
  let body: React.ReactNode;
  if (kind === "pdf") body = <iframe className={css.frame} src={url} title={file} />;
  else if (kind === "image") body = <img className={css.img} src={url} alt={file} />;
  else if (kind === "text") body = <pre className={css.text}>{text}</pre>;
  else body = <div className={ui.empty}>Предпросмотра нет — откройте файл в новой вкладке</div>;
  return (
    <div className={css.source}>
      <div className={css.bar}>
        <button onClick={onBack}>← К листу</button>
        <span className={css.name}>{file}</span>
      </div>
      {body}
    </div>
  );
}
