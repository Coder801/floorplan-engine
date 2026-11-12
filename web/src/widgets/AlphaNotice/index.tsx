// Notice about the product stage on the first visit: a card over everything saying the service
// is in alpha testing. Shown once per browser and stage (seen.ts); "Got it", Esc or a click on
// the veil close it. With onFeedback the feedback point has a "Leave feedback" link: the notice
// closes and the feedback form opens (widgets/Feedback).

import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useFade } from "@/shared/popover";
import { BRAND, STAGE } from "@/shared/version";
import { Button } from "@/ui/Button";
import { Heading } from "@/ui/Heading";
import { Modal } from "@/ui/Modal";
import { Tag } from "@/ui/Tag";
import { Text } from "@/ui/Text";
import { markNoticeSeen, noticeSeen } from "./seen";
import css from "./AlphaNotice.module.scss";

const POINTS = ["errors", "changes", "projects", "feedback"] as const;

export function AlphaNotice({ onFeedback }: { onFeedback?: () => void }) {
  const { t } = useTranslation();
  const fade = useFade();
  const [first] = useState(() => !noticeSeen(STAGE));
  useEffect(() => { if (first) fade.set(true); }, [first]);
  const open = fade.shown && !fade.closing;
  const ok = useRef<HTMLButtonElement>(null);
  const close = () => { markNoticeSeen(STAGE); fade.set(false); };  // fades out (global.scss), then unmounts

  useEffect(() => { if (open) ok.current?.focus(); }, [open]);

  if (!fade.shown) return null;
  return (
    <Modal onClose={close} closing={fade.closing} labelledBy="alpha-title" describedBy="alpha-lead">
      <Tag variant="outline" tone="major" className={css.badge}>{t(`app.stages.${STAGE}`)}</Tag>
      <Heading level={2} size="title" id="alpha-title">
        <span className={css.brand}>{BRAND}</span> {t("alpha.title")}
      </Heading>
      <Text id="alpha-lead">{t("alpha.lead")}</Text>
      <ul className={css.points}>
        {POINTS.map((k) => (
          <li key={k}>
            {t(`alpha.points.${k}`)}
            {k === "feedback" && onFeedback && (
              <> <Button variant="link" className={css.write} onClick={() => { close(); onFeedback(); }}>{t("alpha.write")}</Button></>
            )}
          </li>
        ))}
      </ul>
      <Button ref={ok} variant="primary" size="lg" block onClick={close}>{t("alpha.ok")}</Button>
      <Text size="small" tone="muted">{t("alpha.foot")}</Text>
    </Modal>
  );
}
