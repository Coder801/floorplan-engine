// "What's new" (Settings → "What's new"): the list of product changes by release, newest first, in
// a Modal. Only the list of changes (shared/changelog.ts): no projects, no internal work. The
// entries are the release notes as written (English); headings and dates follow the interface
// language. Esc and a click on the veil close it.

import { useId } from "react";
import { useTranslation } from "react-i18next";
import { CHANGE_KINDS, RELEASES, type Release } from "@/shared/changelog";
import { APP_VERSION } from "@/shared/version";
import { day } from "@/shared/work";
import { Button } from "@/ui/Button";
import { Heading } from "@/ui/Heading";
import { Modal } from "@/ui/Modal";
import { Stack } from "@/ui/Stack";
import { Tag } from "@/ui/Tag";
import { Text } from "@/ui/Text";
import css from "./Changelog.module.scss";

interface Props {
  onClose: () => void;
  releases?: Release[];  // Storybook and tests: without the build-time changelog
}

export function Changelog({ onClose, releases = RELEASES }: Props) {
  const { t, i18n } = useTranslation();
  const title = useId();
  return (
    <Modal size="lg" labelledBy={title} onClose={onClose}>
      <Heading level={2} id={title}>{t("changelog.title")}</Heading>
      <Text tone="muted">{t("changelog.lead")}</Text>
      {releases.length ? (
        <div className={css.releases}>
          {releases.map((r) => (
            <section key={r.version} className={css.release}>
              <header className={css.head}>
                <Heading level={3}>{t("changelog.version", { version: r.version })}</Heading>
                {r.version === APP_VERSION && <Tag>{t("changelog.current")}</Tag>}
                {r.date && <Text as="span" size="small" tone="muted" className={css.date}>{day(r.date, i18n.language)}</Text>}
              </header>
              {CHANGE_KINDS.filter((k) => r.changes[k]?.length).map((k) => (
                <div key={k} className={css.group}>
                  <Heading level={4} size="caps">{t(`changelog.kinds.${k}`)}</Heading>
                  <ul className={css.list}>
                    {r.changes[k]!.map((c, i) => <li key={i}>{c}</li>)}
                  </ul>
                </div>
              ))}
            </section>
          ))}
        </div>
      ) : <Text tone="muted">{t("changelog.empty")}</Text>}
      <Stack direction="row" gap={2}>
        <Button variant="primary" onClick={onClose}>{t("changelog.close")}</Button>
      </Stack>
    </Modal>
  );
}
