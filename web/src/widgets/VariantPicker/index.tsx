// Вариант проводки (docs/wiring-variants.md, манифест .epd — variants): режим (эконом,
// стандарт, премиум) карточками с ценой и отличия режимов списком, трасса и разводка —
// переключателями. Клик только отмечает вариант (pending, «будет выбран») — пересчёт запускает
// страница кнопкой «Пересчитать» (variant.yaml и пересборка, api.saveVariant). Строит все
// варианты код: здесь только сводка.
// Нельзя выбирать (клиент студии) — то же самое без кнопок, с пояснением.
// Трасса одна в проекте (electrical.yaml routes: [ceiling]) — вместо переключателя текст.

import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import ui from "@/shared/styles/ui.module.scss";
import type { VariantMode, VariantRoute, Variants, VariantSummary } from "@/shared/types";
import { MODES, availableRoutes, findVariant, parseKey } from "./variants";
import css from "./VariantPicker.module.scss";

// Чем режимы отличаются в расчёте (docs/wiring-variants.md): трассы, автоматы, щит, гофра
const DETAILS = ["route", "breakers", "panel", "conduit"] as const;

interface Props {
  variants: Variants;
  canChoose: boolean;
  busy: boolean;
  pending: { mode: VariantMode; route: VariantRoute } | null;  // отмечен, ещё не рассчитан
  onPick: (v: { mode: VariantMode; route: VariantRoute } | null) => void;  // null — вернуть текущий
}

export function VariantPicker({ variants, canChoose, busy, pending, onPick }: Props) {
  const { t, i18n } = useTranslation();
  const active = parseKey(variants.active);
  const money = (s: VariantSummary | undefined) =>
    s ? `${Math.round(s.total).toLocaleString(i18n.language)} ${s.currency}` : "—";
  const chosen = pending ?? active;  // что отмечено сейчас: выбранное, а не рассчитанное
  const pick = (mode: VariantMode, route: VariantRoute) => {
    if (!canChoose || busy) return;
    onPick(mode === active.mode && route === active.route ? null : { mode, route });
  };
  const current = findVariant(variants, active.mode, active.route);
  const routes = availableRoutes(variants);
  return (
    <section className={css.picker} aria-busy={busy}>
      <h3>{t("variant.title")}</h3>
      <div className={css.modes} role="radiogroup" aria-label={t("variant.mode")}>
        {MODES.map((mode) => {
          const s = findVariant(variants, mode, chosen.route);
          const on = mode === chosen.mode;
          return (
            <button key={mode} role="radio" aria-checked={on} disabled={!canChoose || busy}
                    className={cx(css.mode, on && (pending ? css.picked : css.on), pending && mode === active.mode && css.on)}
                    onClick={() => pick(mode, chosen.route)}>
              <b>{t(`variant.modes.${mode}`)}</b>
              <span className={css.price}>{money(s)}</span>
              <span className="small muted">{t(`variant.modeNotes.${mode}`)}</span>
              {s?.key === variants.default && <span className={css.tag}>{t("variant.asProject")}</span>}
              {pending && mode === active.mode && <span className={css.tag}>{t("variant.currentTag")}</span>}
              {pending && mode === pending.mode && mode !== active.mode && <span className={cx(css.tag, css.next)}>{t("variant.pickedTag")}</span>}
            </button>
          );
        })}
      </div>
      <details className={css.differences}>
        <summary className="small">{t("variant.differences")}</summary>
        {MODES.map((mode) => (
          <div key={mode} className={cx(css.detail, mode === chosen.mode && css.current)}>
            <b>{t(`variant.modes.${mode}`)}</b>
            <ul>
              {DETAILS.map((d) => <li key={d}>{t(`variant.modeDetails.${mode}.${d}`)}</li>)}
            </ul>
          </div>
        ))}
        <p className="small muted">{t("variant.common")}</p>
      </details>
      <div className={css.row}>
        <span className="small muted">{t("variant.route")}</span>
        {routes.length === 1 ? (
          <span>{t(`variant.routes.${routes[0]}`)} <span className="small muted">· {t("variant.routeOnly")}</span></span>
        ) : (
        <div className={ui.segmented} role="radiogroup" aria-label={t("variant.route")}>
          {routes.map((route) => (
            <button key={route} role="radio" aria-checked={route === chosen.route}
                    className={cx(route === chosen.route && ui.on, pending && route === active.route && css.was)}
                    disabled={!canChoose || busy}
                    title={money(findVariant(variants, chosen.mode, route))}
                    onClick={() => pick(chosen.mode, route)}>
              {t(`variant.routes.${route}`)}
              {pending && route === active.route && <span className="small"> · {t("variant.currentTag")}</span>}
            </button>
          ))}
        </div>
        )}
      </div>
      <div className={css.row}>
        <span className="small muted">{t("variant.distribution")}</span>
        <div className={ui.segmented} role="radiogroup" aria-label={t("variant.distribution")}>
          <button role="radio" aria-checked className={ui.on} disabled={!canChoose || busy}>{t("variant.distributions.boxes")}</button>
          <button role="radio" aria-checked={false} disabled title={t("variant.soon")}>
            {t("variant.distributions.loop")} <span className="small">· {t("variant.soon")}</span>
          </button>
        </div>
      </div>
      {current && (
        <p className="small muted">
          {t("variant.stats", { devices: current.devices, cable: Math.round(current.cable_m), chases: Math.round(current.chases_m) })}
          {current.edited && <> · {t("variant.edited")}</>}
        </p>
      )}
      {pending && !busy && <p className="small">{t("variant.pendingNote")}</p>}
      <p className="small muted">{busy ? t("variant.saving") : canChoose ? t("variant.edits") : t("variant.readOnly")}</p>
    </section>
  );
}
