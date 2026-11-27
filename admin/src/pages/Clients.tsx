// Clients (decision 2026-11-28), full width: the people on the client side, apart from the studios'
// staff. A server-side search (like People) and a filter by how they come to a project: «Мой
// ремонт» (lead it themselves), a client of a studio, no project yet. A row links the person to
// their card in People, the project to Projects and the studio to Studios.
import { useEffect, useMemo, useState } from "react";
import * as api from "@/shared/api";
import { ago, contact, who } from "@/shared/format";
import { href } from "@/shared/route";
import { CLIENT_KIND, CLIENT_KINDS, word } from "@/shared/text";
import { Cols, ErrorLine, Segmented, W, css, useLoad } from "@/components/ui";

export function Clients() {
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("");
  useEffect(() => { const t = setTimeout(() => setSearch(typed.trim()), 250); return () => clearTimeout(t); }, [typed]);
  const list = useLoad(() => api.clients(search), [search]);
  const rows = useMemo(() => (list.data ?? []).filter((c) => !kind || c.kind === kind), [list.data, kind]);
  const count = (k: string) => (list.data ?? []).filter((c) => !k || c.kind === k).length;
  return (
    <>
      <h1 className={css.title}>Клиенты</h1>
      <div className={css.meta}>
        <Segmented options={["", ...CLIENT_KINDS]} value={kind} onChange={setKind}
                   label={(k) => `${k ? word(CLIENT_KIND, k) : "все"}${list.data ? ` ${count(k)}` : ""}`} />
        <input placeholder="Имя, почта или телефон" value={typed} onChange={(e) => setTyped(e.target.value)} />
      </div>
      <ErrorLine error={list.error} />
      {list.data && !rows.length && <div className={css.empty}>Клиентов нет</div>}
      {rows.length > 0 && (
        <table><Cols w={[null, null, W.role, null, null, W.ago]} />
          <thead><tr><th>Клиент</th><th>Контакт</th><th>Вид</th><th>Проект</th><th>Студия</th><th>Вход</th></tr></thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.user.id}>
                <td title={who(c.user)}><a className={css.link} href={href("users", c.user.id)}>{who(c.user)}</a></td>
                <td className={css.muted} title={contact(c.user)}>{contact(c.user)}</td>
                <td>{word(CLIENT_KIND, c.kind)}</td>
                <td title={c.project?.name}>
                  {c.project ? <a className={css.link} href={href("projects", c.project.id)}>{c.project.name}</a> : <span className={css.muted}>—</span>}
                </td>
                <td title={c.studio?.name}>
                  {c.kind === "personal" ? <span className={css.muted}>сам</span>
                    : c.studio ? <a className={css.link} href={href("studios", c.studio.id)}>«{c.studio.name}»</a>
                    : <span className={css.muted}>—</span>}
                </td>
                <td className={css.mono}>{ago(c.user.last_login)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
