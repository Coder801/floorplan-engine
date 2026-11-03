// Studios: list with a kind filter; detail with members (role changes at once), projects and
// invites. Only a firm has employees: "Мой ремонт" and "без владельца" say why there is no button.
import { useMemo, useState } from "react";
import * as api from "@/shared/api";
import { contact, date, who } from "@/shared/format";
import { href } from "@/shared/route";
import { BUSINESS, KIND, ROLE, STUDIO_ROLES, word } from "@/shared/text";
import type { StudioDetail, StudioRow } from "@/shared/types";
import { IssueForm, OneTime, PersonPicker } from "@/components/dialogs";
import { Confirm, ErrorLine, Section, Status, css, cx, useAction, useLoad } from "@/components/ui";

export function StudioList({ id, version }: { id: string | null; version: number }) {
  const list = useLoad(api.studios, [version]);
  const [q, setQ] = useState("");
  const [kind, setKind] = useState("");
  const rows = useMemo(
    () => (list.data ?? []).filter((s) => (!kind || s.kind === kind) && s.name.toLowerCase().includes(q.toLowerCase())),
    [list.data, q, kind],
  );
  return (
    <>
      <div className={css.listHead}>
        <input placeholder="Название" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={kind} onChange={(e) => setKind(e.target.value)}>
          <option value="">Все виды</option>
          {Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
      </div>
      <div className={css.listBody}>
        <ErrorLine error={list.error} />
        {rows.map((s: StudioRow) => (
          <a key={s.id} href={href("studios", s.id)} className={cx(css.row, s.id === id && css.on)}>
            <div className={css.rowTop}><span>{s.name}</span><span className={css.muted}>{word(KIND, s.kind)}</span></div>
            <div className={css.rowSub}>{s.members} уч. · {s.projects} пр.{s.city ? ` · ${s.city}` : ""}</div>
          </a>
        ))}
      </div>
    </>
  );
}

export function StudioView({ id, onChanged }: { id: string; onChanged: () => void }) {
  const detail = useLoad(() => api.studio(id), [id]);
  const action = useAction();
  const [adding, setAdding] = useState(false);
  const [inviting, setInviting] = useState(false);
  const [link, setLink] = useState<string | null>(null);
  const s = detail.data;
  if (detail.error) return <ErrorLine error={detail.error} />;
  if (!s) return <div className={css.muted}>Загрузка…</div>;
  const firm = s.kind === "studio";
  const update = (d: StudioDetail) => { detail.set(d); onChanged(); };
  return (
    <>
      <a className={css.back} href={href("studios")}>← К списку</a>
      <h1 className={css.title}>{s.name}</h1>
      <div className={css.meta}>
        <span>{word(KIND, s.kind)}</span>
        {s.business && <span>{word(BUSINESS, s.business)}</span>}
        {s.city && <span>{s.city}</span>}
        {s.phone && <span>{s.phone}</span>}
        <span>папка <span className={css.mono}>{s.folder === "" ? "корень" : s.folder}</span></span>
        <span>с {date(s.created, false)}</span>
      </div>

      <Section title={`Участники (${s.members.length})`}
        action={firm && <span className={css.actions}>
          <button onClick={() => setInviting(true)}>Ссылка</button>
          <button className={css.primary} onClick={() => setAdding(true)}>+ Добавить</button>
        </span>}>
        {!firm && <div className={css.muted}>{s.kind === "personal" ? "В «Моём ремонте» только владелец." : "У проектов без владельца участников нет."}</div>}
        <table><tbody>
          {s.members.map((m) => (
            <tr key={m.user.id}>
              <td><a className={css.link} href={href("users", m.user.id)}>{who(m.user)}</a></td>
              <td className={css.muted}>{contact(m.user)}</td>
              <td>
                {firm ? (
                  <select value={m.role} disabled={action.busy}
                    onChange={(e) => action.run(() => api.setStudioRole(id, m.user.id, e.target.value), update)}>
                    {STUDIO_ROLES.map((r) => <option key={r} value={r}>{word(ROLE, r)}</option>)}
                  </select>
                ) : word(ROLE, m.role)}
              </td>
              <td className={css.mono}>с {date(m.since, false)}</td>
              <td className={css.actions}>
                {firm && <Confirm label="Убрать" question={`Убрать ${who(m.user)}?`}
                  onYes={() => action.run(() => api.removeStudioMember(id, m.user.id), update)} />}
              </td>
            </tr>
          ))}
        </tbody></table>
        <ErrorLine error={action.error} />
      </Section>

      <Section title={`Проекты (${s.projects.length})`}>
        {s.projects.length === 0 && <div className={css.empty}>Проектов нет</div>}
        <table><tbody>
          {s.projects.map((p) => (
            <tr key={p.id}>
              <td><a className={css.link} href={href("projects", p.id)}><span className={css.mono}>{p.slug}</span></a></td>
              <td>{p.name}</td>
              <td className={css.mono}>{date(p.created, false)}</td>
            </tr>
          ))}
        </tbody></table>
      </Section>

      {s.invites.length > 0 && (
        <Section title="Приглашения в студию">
          <table><tbody>
            {s.invites.map((i) => (
              <tr key={i.id}>
                <td>{word(ROLE, i.role)}</td>
                <td className={css.muted}>{i.email ?? "—"}</td>
                <td><Status state={i.state} label={i.state === "accepted" ? `принял ${who(i.accepted_by)}` : undefined} /></td>
                <td className={css.mono}>до {date(i.expires, false)}</td>
                <td className={css.actions}>
                  {i.state === "active" && <Confirm label="Отозвать" question="Отозвать ссылку?"
                    onYes={() => action.run(() => api.revokeInvite(i.id), () => detail.reload())} />}
                </td>
              </tr>
            ))}
          </tbody></table>
        </Section>
      )}

      {adding && (
        <PersonPicker title={`Сотрудник в «${s.name}»`} roles={STUDIO_ROLES}
          unfit={(u) => s.members.some((m) => m.user.id === u.id) ? "уже здесь"
            : u.account_type === "client" ? "хозяин квартиры"
            : u.space ? `уже в «${u.space.name}»` : null}
          onPick={(u, role) => api.addStudioMember(id, u.id, role).then(update)}
          onInvite={() => { setAdding(false); setInviting(true); }}
          onClose={() => setAdding(false)} />
      )}
      {inviting && (
        <IssueForm title="Ссылка-приглашение в студию" roles={["designer", "installer"]} textLabel="Почта (для списка)" days={7}
          onIssue={(role, email, days) => api.studioInvite(id, role, email || null, days).then((r) => r.url)}
          onClose={(v) => { setInviting(false); setLink(v); if (v) detail.reload(); }} />
      )}
      {link && <OneTime title="Ссылка-приглашение" value={link} onClose={() => setLink(null)} />}
    </>
  );
}
