// Audit log, full width: filtered by project and author from the address (links from the
// records), and by action over the loaded rows; a row opens its payload.
import { useMemo, useState } from "react";
import * as api from "@/shared/api";
import { date, who } from "@/shared/format";
import { href } from "@/shared/route";
import { ACTION, word } from "@/shared/text";
import type { EventRow } from "@/shared/types";
import { ErrorLine, css, useLoad } from "@/components/ui";

export function EventTable({ rows, compact }: { rows: EventRow[]; compact?: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <table>
      <thead><tr><th>Когда</th><th>Кто</th><th>Что</th><th>Кого</th>{!compact && <th>Проект</th>}</tr></thead>
      <tbody>
        {rows.map((e) => (
          <tr key={e.id} onClick={() => setOpen(open === e.id ? null : e.id)} style={{ cursor: "pointer" }}>
            <td className={css.mono}>{date(e.at)}</td>
            <td>{e.user ? <a className={css.link} href={href("users", e.user.id)} onClick={(ev) => ev.stopPropagation()}>{who(e.user)}</a> : "—"}</td>
            <td>
              {word(ACTION, e.action)}
              {open === e.id && <pre className={css.payload}>{JSON.stringify(e.payload, null, 2)}</pre>}
            </td>
            <td>
              {e.subject ? <a className={css.link} href={href("users", e.subject.id)} onClick={(ev) => ev.stopPropagation()}>{who(e.subject)}</a> : ""}
              {e.studio ? <a className={css.link} href={href("studios", e.studio.id)} onClick={(ev) => ev.stopPropagation()}> «{e.studio.name}»</a> : ""}
            </td>
            {!compact && <td className={css.mono}>{e.project ?? ""}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function Events({ params }: { params: URLSearchParams }) {
  const project = params.get("project") ?? undefined;
  const user = params.get("user") ?? undefined;
  const [limit, setLimit] = useState(200);
  const [action, setAction] = useState("");
  const log = useLoad(() => api.events({ project, user, limit }), [project, user, limit]);
  const rows = useMemo(() => (log.data ?? []).filter((e) => !action || e.action === action), [log.data, action]);
  const actions = useMemo(() => [...new Set((log.data ?? []).map((e) => e.action))].sort(), [log.data]);
  return (
    <>
      <h1 className={css.title}>Журнал</h1>
      <div className={css.meta}>
        {project && <span>проект <span className={css.mono}>{rows[0]?.project ?? project}</span> <a className={css.link} href={href("events", null, user ? { user } : {})}>×</a></span>}
        {user && <span>автор {who(rows.find((e) => e.user?.id === user)?.user)} <a className={css.link} href={href("events", null, project ? { project } : {})}>×</a></span>}
        <select value={action} onChange={(e) => setAction(e.target.value)}>
          <option value="">Все действия</option>
          {actions.map((a) => <option key={a} value={a}>{word(ACTION, a)}</option>)}
        </select>
        <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
          {[200, 500, 1000].map((n) => <option key={n} value={n}>последние {n}</option>)}
        </select>
      </div>
      <ErrorLine error={log.error} />
      <EventTable rows={rows} />
    </>
  );
}
