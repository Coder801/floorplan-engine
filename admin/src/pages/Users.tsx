// People: server-side search, a filter by account type; detail with the workspace, projects,
// login methods and sessions; block (ends the sessions) and "end all sessions". Your own record
// cannot be blocked.
import { useEffect, useMemo, useState } from "react";
import * as api from "@/shared/api";
import { ago, contact, date, who } from "@/shared/format";
import { href } from "@/shared/route";
import { ACCOUNT, KIND, ROLE, word } from "@/shared/text";
import type { UserDetail } from "@/shared/types";
import { Confirm, ErrorLine, Section, Status, css, cx, useAction, useLoad } from "@/components/ui";

export function UserList({ id, version }: { id: string | null; version: number }) {
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [account, setAccount] = useState("");
  useEffect(() => { const t = setTimeout(() => setSearch(q), 250); return () => clearTimeout(t); }, [q]);
  const list = useLoad(() => api.users(search), [search, version]);
  const rows = useMemo(
    () => (list.data ?? []).filter((u) => !account || (u.account_type ?? "none") === account),
    [list.data, account],
  );
  return (
    <>
      <div className={css.listHead}>
        <input placeholder="Имя, почта или телефон" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={account} onChange={(e) => setAccount(e.target.value)}>
          <option value="">Все учётки</option>
          <option value="pro">студия</option>
          <option value="client">хозяин квартиры</option>
          <option value="none">не выбрана</option>
        </select>
      </div>
      <div className={css.listBody}>
        <ErrorLine error={list.error} />
        {rows.map((u) => (
          <a key={u.id} href={href("users", u.id)} className={cx(css.row, u.id === id && css.on)}>
            <div className={css.rowTop}>
              <span>{who(u)}</span>
              {u.active ? <span className={css.muted}>{ago(u.last_login)}</span> : <Status state="blocked" label="заблокирован" />}
            </div>
            <div className={css.rowSub}>{contact(u)}{u.space ? ` · «${u.space.name}»` : ""}</div>
          </a>
        ))}
      </div>
    </>
  );
}

export function UserView({ id, me, onChanged }: { id: string; me: string; onChanged: () => void }) {
  const detail = useLoad(() => api.user(id), [id]);
  const action = useAction();
  const u = detail.data;
  if (detail.error) return <ErrorLine error={detail.error} />;
  if (!u) return <div className={css.muted}>Загрузка…</div>;
  const self = u.id === me;
  const update = (d: UserDetail) => { detail.set(d); onChanged(); };
  return (
    <>
      <a className={css.back} href={href("users")}>← К списку</a>
      <h1 className={css.title}>{who(u)}{self && <span className={css.muted}> · это вы</span>}</h1>
      <div className={css.meta}>
        <span>{contact(u)}</span>
        <span>{word(ACCOUNT, u.account_type)}</span>
        {u.superuser && <span>владелец платформы</span>}
        <span>{u.active ? <Status state="active" label="активен" /> : <Status state="blocked" label="заблокирован" />}</span>
        <span>с {date(u.created, false)}</span>
        <span>вход {ago(u.last_login)}</span>
        <a className={css.link} href={href("events", null, { user: u.id })}>журнал</a>
      </div>
      <div className={css.actions} style={{ justifyContent: "flex-start" }}>
        <Confirm label="Завершить сеансы" question="Выкинуть из всех сеансов?" disabled={u.sessions.length === 0}
          onYes={() => action.run(() => api.logout(id), update)} />
        {u.active
          ? <Confirm label="Заблокировать" question="Заблокировать и выкинуть?" disabled={self}
              onYes={() => action.run(() => api.setActive(id, false), update)} />
          : <button onClick={() => action.run(() => api.setActive(id, true), update)}>Разблокировать</button>}
      </div>
      <ErrorLine error={action.error} />

      <Section title="Пространство">
        {u.space ? (
          <div><a className={css.link} href={href("studios", u.space.id)}>«{u.space.name}»</a>
            <span className={css.muted}> · {word(KIND, u.space.kind)} · {word(ROLE, u.space.role)}</span></div>
        ) : <div className={css.empty}>Нет</div>}
      </Section>
      <Section title={`Проекты по приглашению (${u.projects.length})`}>
        {u.projects.length === 0 && <div className={css.empty}>Нет</div>}
        <table><tbody>
          {u.projects.map((p) => (
            <tr key={p.id}>
              <td><a className={css.link} href={href("projects", p.id)}><span className={css.mono}>{p.slug}</span></a></td>
              <td>{p.name}</td><td>{word(ROLE, p.role)}</td><td className={css.muted}>«{p.studio.name}»</td>
            </tr>
          ))}
        </tbody></table>
      </Section>
      <Section title="Вход">
        <div>{u.providers.join(", ") || "—"}</div>
      </Section>
      <Section title={`Сеансы (${u.sessions.length})`}>
        {u.sessions.length === 0 && <div className={css.empty}>Нет действующих</div>}
        <table><tbody>
          {u.sessions.map((s) => (
            <tr key={s.id}>
              <td className={css.muted} style={{ maxWidth: 360, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.agent || "—"}</td>
              <td className={css.mono}>с {date(s.created)}</td><td className={css.mono}>{ago(s.seen)}</td>
            </tr>
          ))}
        </tbody></table>
      </Section>
    </>
  );
}
