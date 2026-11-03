// Start page: counts as links to the lists and the last events.
import * as api from "@/shared/api";
import { href } from "@/shared/route";
import { ErrorLine, Section, css, useLoad } from "@/components/ui";
import { EventTable } from "./Events";

export function Summary() {
  const counts = useLoad(api.summary, []);
  const log = useLoad(() => api.events({ limit: 15 }), []);
  const c = counts.data;
  return (
    <>
      <h1 className={css.title}>Сводка</h1>
      <ErrorLine error={counts.error ?? log.error} />
      {c && (
        <div className={css.cards} style={{ marginTop: 12 }}>
          <a className={css.card} href={href("studios")}><b>{c.studios}</b>фирм</a>
          <a className={css.card} href={href("studios")}><b>{c.personal}</b>«Мой ремонт»</a>
          <a className={css.card} href={href("users")}><b>{c.users}</b>людей</a>
          <a className={css.card} href={href("projects")}><b>{c.projects}</b>проектов</a>
          <a className={css.card} href={href("users")}><b>{c.sessions}</b>сеансов</a>
        </div>
      )}
      <Section title="Последние события" action={<a className={css.link} href={href("events")}>весь журнал</a>}>
        <EventTable rows={log.data ?? []} />
      </Section>
    </>
  );
}
