// Projects: list; detail with members (client, outside installer), access codes (shown once),
// invite links and support access. Every section has its own add button.
import { useMemo, useState } from "react";
import * as api from "@/shared/api";
import { ago, contact, date, who } from "@/shared/format";
import { href } from "@/shared/route";
import { PROJECT_ROLES, ROLE, word } from "@/shared/text";
import type { ProjectDetail } from "@/shared/types";
import { IssueForm, OneTime, PersonPicker } from "@/components/dialogs";
import { Confirm, ErrorLine, Section, Status, css, cx, useAction, useLoad } from "@/components/ui";

export function ProjectList({ id, version }: { id: string | null; version: number }) {
  const list = useLoad(api.projects, [version]);
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    const s = q.toLowerCase();
    return (list.data ?? []).filter((p) =>
      [p.slug ?? "", p.name, p.studio.name].some((t) => t.toLowerCase().includes(s)));
  }, [list.data, q]);
  return (
    <>
      <div className={css.listHead}>
        <input placeholder="Папка, название или студия" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <div className={css.listBody}>
        <ErrorLine error={list.error} />
        {rows.map((p) => (
          <a key={p.id} href={href("projects", p.id)} className={cx(css.row, p.id === id && css.on)}>
            <div className={css.rowTop}><span className={css.mono}>{p.slug}</span><span className={css.muted}>{p.members} уч.</span></div>
            <div className={css.rowSub}>{p.name} · «{p.studio.name}»</div>
          </a>
        ))}
      </div>
    </>
  );
}

type Dialogs = "member" | "code" | "invite" | "support" | null;

export function ProjectView({ id, onChanged }: { id: string; onChanged: () => void }) {
  const detail = useLoad(() => api.project(id), [id]);
  const action = useAction();
  const [open, setOpen] = useState<Dialogs>(null);
  const [secret, setSecret] = useState<{ title: string; value: string } | null>(null);
  const p = detail.data;
  if (detail.error) return <ErrorLine error={detail.error} />;
  if (!p) return <div className={css.muted}>Загрузка…</div>;
  const update = (d: ProjectDetail) => { detail.set(d); onChanged(); };
  const issued = (title: string) => (v: string | null) => {
    setOpen(null);
    if (v) { setSecret({ title, value: v }); detail.reload(); }
  };
  return (
    <>
      <a className={css.back} href={href("projects")}>← К списку</a>
      <h1 className={css.title}><span className={css.mono}>{p.slug}</span> · {p.name}</h1>
      <div className={css.meta}>
        <a className={css.link} href={href("studios", p.studio.id)}>«{p.studio.name}»</a>
        <span>с {date(p.created, false)}</span>
        <a className={css.link} href={href("events", null, { project: p.id })}>журнал</a>
        <a className={css.link} href={`/#${encodeURIComponent(p.id)}`} target="_blank" rel="noreferrer">открыть в просмотре ↗</a>
      </div>
      <ErrorLine error={action.error} />

      <Section title={`Участники (${p.members.length})`}
        action={<button className={css.primary} onClick={() => setOpen("member")}>+ Добавить</button>}>
        {p.members.length === 0 && <div className={css.empty}>Только студия проекта</div>}
        <table><tbody>
          {p.members.map((m) => (
            <tr key={m.user.id}>
              <td><a className={css.link} href={href("users", m.user.id)}>{who(m.user)}</a></td>
              <td className={css.muted}>{contact(m.user)}</td>
              <td>{word(ROLE, m.role)}</td>
              <td className={css.mono}>с {date(m.since, false)}</td>
              <td className={css.actions}>
                <Confirm label="Убрать" question={`Убрать ${who(m.user)}?`}
                  onYes={() => action.run(() => api.removeProjectMember(id, m.user.id), update)} />
              </td>
            </tr>
          ))}
        </tbody></table>
      </Section>

      <Section title={`Коды доступа (${p.codes.length})`}
        action={<button onClick={() => setOpen("code")}>+ Выдать</button>}>
        {p.codes.length === 0 && <div className={css.empty}>Кодов нет</div>}
        {p.codes.length > 0 && (
          <table>
            <thead><tr><th>Кому</th><th>Статус</th><th>Входов</th><th>Выдан</th><th>До</th><th>Последний вход</th><th /></tr></thead>
            <tbody>
              {p.codes.map((c) => (
                <tr key={c.id}>
                  <td>{c.label || "—"}</td><td><Status state={c.state} /></td>
                  <td className={css.mono}>{c.uses}</td>
                  <td className={css.mono}>{date(c.created, false)}</td>
                  <td className={css.mono}>{date(c.expires, false)}</td>
                  <td className={css.mono}>{ago(c.last_used)}</td>
                  <td className={css.actions}>
                    {c.state === "active" && <Confirm label="Отозвать" question="Отозвать код?"
                      onYes={() => action.run(() => api.revokeCode(id, c.id), update)} />}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Section>

      <Section title={`Приглашения (${p.invites.length})`}
        action={<button onClick={() => setOpen("invite")}>+ Ссылка</button>}>
        {p.invites.length === 0 && <div className={css.empty}>Приглашений нет</div>}
        <table><tbody>
          {p.invites.map((i) => (
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

      <Section title={`Поддержка (${p.support.length})`}
        action={<button onClick={() => setOpen("support")}>+ Открыть доступ</button>}>
        {p.support.length === 0 && <div className={css.empty}>Доступа поддержки нет</div>}
        <table><tbody>
          {p.support.map((g, n) => (
            <tr key={`${g.user.id}-${n}`}>
              <td><a className={css.link} href={href("users", g.user.id)}>{who(g.user)}</a></td>
              <td className={css.muted}>«{g.reason}»</td>
              <td><Status state={g.state} /></td>
              <td className={css.mono}>до {date(g.expires)}</td>
              <td className={css.actions}>
                {g.state === "active" && <Confirm label="Снять" question="Снять доступ?"
                  onYes={() => action.run(() => api.revokeSupport(id, g.user.id), update)} />}
              </td>
            </tr>
          ))}
        </tbody></table>
      </Section>

      {open === "member" && (
        <PersonPicker title={`Участник проекта ${p.slug}`} roles={PROJECT_ROLES}
          unfit={(u) => p.members.some((m) => m.user.id === u.id) ? "уже здесь"
            : u.space?.id === p.studio.id ? "в студии проекта" : null}
          onPick={(u, role) => api.addProjectMember(id, u.id, role).then(update)}
          onInvite={() => setOpen("invite")}
          onClose={() => setOpen(null)} />
      )}
      {open === "support" && (
        <PersonPicker title="Доступ поддержки на 72 часа" roles={["support"]}
          extra={{ label: "Причина", placeholder: "Причина: что чинить" }}
          onPick={(u, _role, reason) => api.grantSupport(id, u.id, reason, 72).then(update)}
          onClose={() => setOpen(null)} />
      )}
      {open === "code" && (
        <IssueForm title="Код доступа к проекту" textLabel="Кому (подпись в списке)" days={30}
          onIssue={(_r, label, days) => api.issueCode(id, label, days).then((r) => r.code)}
          onClose={issued("Код доступа")} />
      )}
      {open === "invite" && (
        <IssueForm title="Ссылка-приглашение в проект" roles={PROJECT_ROLES} textLabel="Почта (для списка)" days={7}
          onIssue={(role, email, days) => api.projectInvite(id, role, email || null, days).then((r) => r.url)}
          onClose={issued("Ссылка-приглашение")} />
      )}
      {secret && <OneTime title={secret.title} value={secret.value} onClose={() => setSecret(null)} />}
    </>
  );
}
