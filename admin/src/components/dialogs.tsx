// Dialogs: pick a person from the database (members, support), and show a one-time code or invite
// link — the API never returns them again.
import { useEffect, useState } from "react";
import * as api from "@/shared/api";
import { contact, who } from "@/shared/format";
import { ACCOUNT, ROLE, word } from "@/shared/text";
import type { UserRow } from "@/shared/types";
import { Dialog, ErrorLine, Segmented, css, cx, useAction } from "./ui";

/** Search people (250 ms after typing stops), pick one and a role; the server decides, and its
 *  409 reason stays in the dialog. unfit says why a person cannot be picked (greyed out). */
export function PersonPicker({ title, roles, unfit, onPick, onClose, onInvite, extra }: {
  title: string;
  roles: string[];
  unfit?: (u: UserRow) => string | null;
  onPick: (user: UserRow, role: string, text: string) => Promise<unknown>;
  onClose: () => void;
  onInvite?: () => void;
  extra?: { label: string; placeholder: string };
}) {
  const [q, setQ] = useState("");
  const [found, setFound] = useState<UserRow[]>([]);
  const [picked, setPicked] = useState<UserRow | null>(null);
  const [role, setRole] = useState(roles[0]);
  const [text, setText] = useState("");
  const action = useAction();
  useEffect(() => {
    const t = setTimeout(() => { api.users(q).then(setFound).catch(() => setFound([])); }, 250);
    return () => clearTimeout(t);
  }, [q]);
  const submit = () => picked && action.run(() => onPick(picked, role, text), onClose);
  return (
    <Dialog title={title} onClose={onClose}>
      <input autoFocus placeholder="Имя, почта или телефон" value={q} onChange={(e) => setQ(e.target.value)} />
      <div style={{ maxHeight: 260, overflow: "auto" }}>
        {found.length === 0 && <div className={css.empty}>Никого не нашлось</div>}
        {found.map((u) => {
          const why = unfit?.(u) ?? null;
          return (
            <button key={u.id} disabled={why !== null} className={cx(css.pick, picked?.id === u.id && css.on)}
              onClick={() => setPicked(u)}>
              <span>{who(u)} <span className={css.muted}>· {word(ACCOUNT, u.account_type)}</span></span>
              <span className={css.muted}>{contact(u)}{u.space ? ` · «${u.space.name}»` : ""}{why ? ` — ${why}` : ""}</span>
            </button>
          );
        })}
      </div>
      {roles.length > 1 && <div><Segmented options={roles} value={role} onChange={setRole} label={(r) => word(ROLE, r)} /></div>}
      {extra && <input placeholder={extra.placeholder} aria-label={extra.label} value={text} onChange={(e) => setText(e.target.value)} />}
      <ErrorLine error={action.error} />
      <div className={css.actions}>
        {onInvite && <button className={css.link} style={{ marginRight: "auto", border: 0, background: "none" }} onClick={onInvite}>Нет в списке? Ссылка-приглашение</button>}
        <button onClick={onClose}>Отмена</button>
        <button className={css.primary} disabled={!picked || action.busy || (extra !== undefined && !text.trim())} onClick={submit}>Добавить</button>
      </div>
    </Dialog>
  );
}

/** A code or a link, shown once: big, with a copy button. */
export function OneTime({ title, value, onClose }: { title: string; value: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const link = value.includes("://");
  return (
    <Dialog title={title} onClose={onClose}>
      <div className={cx(css.reveal, link && css.small)}>{value}</div>
      <div className={css.muted}>Показывается один раз: в списках потом его не будет.</div>
      <div className={css.actions}>
        <button onClick={() => navigator.clipboard.writeText(value).then(() => setCopied(true))}>
          {copied ? "Скопировано" : "Скопировать"}
        </button>
        <button className={css.primary} onClick={onClose}>Скопировал, закрыть</button>
      </div>
    </Dialog>
  );
}

/** New code or invite: a role (for invites), a label or e-mail, a term in days. */
export function IssueForm({ title, roles, textLabel, days, onIssue, onClose }: {
  title: string;
  roles?: string[];
  textLabel: string;
  days: number;
  onIssue: (role: string, text: string, days: number) => Promise<string>;
  onClose: (value: string | null) => void;
}) {
  const [role, setRole] = useState(roles?.[0] ?? "");
  const [text, setText] = useState("");
  const [term, setTerm] = useState(days);
  const action = useAction();
  return (
    <Dialog title={title} onClose={() => onClose(null)}>
      {roles && <div><Segmented options={roles} value={role} onChange={setRole} label={(r) => word(ROLE, r)} /></div>}
      <input autoFocus placeholder={textLabel} value={text} onChange={(e) => setText(e.target.value)} />
      <label>Срок, дней <input type="number" min={1} value={term} onChange={(e) => setTerm(Number(e.target.value))} style={{ width: 80 }} /></label>
      <ErrorLine error={action.error} />
      <div className={css.actions}>
        <button onClick={() => onClose(null)}>Отмена</button>
        <button className={css.primary} disabled={action.busy}
          onClick={() => action.run(() => onIssue(role, text.trim(), term), (v) => onClose(v))}>Выдать</button>
      </div>
    </Dialog>
  );
}
