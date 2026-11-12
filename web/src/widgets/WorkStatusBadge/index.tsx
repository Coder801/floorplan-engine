// A task status as a coloured pill: the same colours as the board columns; big — for the
// client's list on a phone

import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import type { WorkStatus } from "@/shared/types";
import css from "./WorkStatusBadge.module.scss";

export function WorkStatusBadge({ status, big }: { status: WorkStatus; big?: boolean }) {
  const { t } = useTranslation();
  return <span className={cx(css.badge, big && css.big)} data-status={status}>{t(`work.status.${status}`)}</span>;
}
