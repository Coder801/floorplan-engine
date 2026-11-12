// "Backup" mode of the "Panel" page: which groups stay on when the grid is down. Saved as the
// panel_reserve answer, with a rebuild: the groups move to the backup rail. Read only without the
// right to answer, or when electrical.yaml fixes the list (there is no question then).

import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import type { OverviewReserve } from "@/shared/types";
import { Button } from "@/ui/Button";
import { Card } from "@/ui/Card";
import { Heading } from "@/ui/Heading";
import { Text } from "@/ui/Text";
import { ReserveList } from "@/widgets/ReserveList";
import { reserveOn } from "@/widgets/ReserveList/reserve";
import css from "./ReserveStage.module.scss";

interface Props {
  reserve: OverviewReserve;
  editable: boolean;
  busy: boolean;
  onSave: (groups: string[]) => Promise<void>;
}

export function ReserveStage({ reserve, editable, busy, onSave }: Props) {
  const { t } = useTranslation();
  const start = reserveOn(reserve).join();
  const [value, setValue] = useState(() => reserveOn(reserve));
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setValue(start ? start.split(",") : []); }, [start]);
  const dirty = value.join() !== start;
  const save = () => {
    setError(null);
    onSave(value).catch((e: Error) => setError(t("reserve.failed", { message: e.message })));
  };
  return (
    <div className={css.stage}>
      <Card variant="panel" padding="none" className={css.sheet}>
        <Heading level={1} className={css.title}>{t("reserve.title")}</Heading>
        <Text tone="muted">{t("reserve.why")}</Text>
        <ReserveList reserve={reserve} value={value} disabled={!editable || busy} onChange={setValue} />
        {!value.length && <Text tone="major">{t("reserve.empty")}</Text>}
        {error && <Text tone="major" role="alert">{error}</Text>}
        {editable
          ? <Button variant="primary" className={css.save} disabled={!dirty || !value.length || busy} onClick={save}>{t("reserve.save")}</Button>
          : <Text size="small" tone="muted">{t("reserve.readOnly")}</Text>}
      </Card>
    </div>
  );
}
