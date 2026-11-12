// Admin layout (variant B, decision 2026-11-03): sections | list | detail. The summary and the log
// take the list and detail columns together. Only an active platform owner gets in: the API
// answers 403 to others, and the page says so before asking for anything.
import { useCallback, useState } from "react";
import * as api from "@/shared/api";
import { who } from "@/shared/format";
import { SECTIONS, href, useRoute } from "@/shared/route";
import { SECTION } from "@/shared/text";
import { css, cx, useLoad } from "@/components/ui";
import { Events } from "@/pages/Events";
import { Feedback } from "@/pages/Feedback";
import { ProjectList, ProjectView } from "@/pages/Projects";
import { StudioList, StudioView } from "@/pages/Studios";
import { Summary } from "@/pages/Summary";
import { UserList, UserView } from "@/pages/Users";

export function App() {
  const me = useLoad(api.me, []);
  if (me.error) return <div className={css.gate}><div className={css.error}>{me.error}</div></div>;
  if (!me.data) return <div className={css.gate}><span className={css.muted}>Загрузка…</span></div>;
  const user = me.data.user;
  if (!me.data.auth) return <Gate text="Вход в сервис выключен (SHTROBA_AUTH): админке нужна база и вход." />;
  if (!user) return <Gate text="Сначала войдите в просмотр." link />;
  if (!user.superuser) return <Gate text="Админка — только для владельца платформы." link />;
  return <Admin me={user.id} name={who(user)} />;
}

function Gate({ text, link }: { text: string; link?: boolean }) {
  return (
    <div className={css.gate}>
      <div><div className={css.brand}>Shtroba<span className={css.brandSub}>admin</span></div>
        <p>{text}</p>{link && <a className={css.link} href="/">Открыть просмотр и войти</a>}</div>
    </div>
  );
}

function Admin({ me, name }: { me: string; name: string }) {
  const route = useRoute();
  // A change in a detail refreshes the counts of its list
  const [version, setVersion] = useState(0);
  const changed = useCallback(() => setVersion((v) => v + 1), []);
  const wide = route.section === "summary" || route.section === "events" || route.section === "feedback";
  // New feedback is counted next to its section
  const fresh = useLoad(() => api.feedback({ status: "new", limit: 1 }), [version]);
  const unread = fresh.data?.counts.new ?? 0;
  return (
    <div className={cx(css.shell, wide && css.wide, route.id && css.hasDetail)}>
      <nav className={css.nav}>
        <div className={css.brand}>Shtroba<span className={css.brandSub}>admin</span></div>
        {SECTIONS.map((s) => (
          <a key={s} href={href(s)} className={cx(css.navItem, route.section === s && css.on)}>
            {SECTION[s]}{s === "feedback" && unread > 0 && <span className={css.badge}>{unread}</span>}
          </a>
        ))}
        <div className={css.navFoot}><span>{name}</span><a className={css.link} href="/">Просмотр ↗</a></div>
      </nav>
      {!wide && (
        <div className={css.list}>
          {route.section === "studios" && <StudioList id={route.id} version={version} />}
          {route.section === "users" && <UserList id={route.id} version={version} />}
          {route.section === "projects" && <ProjectList id={route.id} version={version} />}
        </div>
      )}
      <main className={css.detail}>
        {route.section === "summary" && <Summary />}
        {route.section === "events" && <Events params={route.params} />}
        {route.section === "feedback" && <Feedback onChanged={changed} />}
        {!wide && !route.id && <div className={css.empty}>Выберите запись в списке</div>}
        {route.section === "studios" && route.id && <StudioView key={route.id} id={route.id} onChanged={changed} />}
        {route.section === "users" && route.id && <UserView key={route.id} id={route.id} me={me} onChanged={changed} />}
        {route.section === "projects" && route.id && <ProjectView key={route.id} id={route.id} onChanged={changed} />}
      </main>
    </div>
  );
}
