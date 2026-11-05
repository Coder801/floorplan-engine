// Stickers of the panel: rail by rail, as they go on the devices. Geometry comes ready from the
// core (sheets/stickers.py, key panel.stickers), the same as in the PDF out/panel-stickers.pdf.

import { useTranslation } from "react-i18next";
import type { PanelSticker, PanelStickers } from "@/shared/types";
import css from "./StickersStage.module.scss";

interface Props {
  stickers: PanelStickers;
  pdf: string | null;   // the file of the build; an older build has none
}

export function StickersStage({ stickers, pdf }: Props) {
  const { t } = useTranslation();
  const rails = [...new Set(stickers.items.map((s) => s.row))];
  return (
    <div className={css.stage}>
      <article className={css.sheet}>
        <header className={css.head}>
          <div>
            <h1>{t("panel.stickers")}</h1>
            <p>{t("panel.stickersNote", { n: stickers.items.length, width: stickers.width, height: stickers.height })}</p>
          </div>
          {pdf && <a className={css.pdf} href={pdf} download>{t("panel.stickersPdf")}</a>}
        </header>
        {rails.map((row, i) => (
          <section key={row}>
            <h2>{t("panel.rail", { n: i + 1 })}</h2>
            <div className={css.rail}>
              {stickers.items.filter((s) => s.row === row).map((s) => <Sticker key={s.id} item={s} stickers={stickers} />)}
            </div>
          </section>
        ))}
      </article>
    </div>
  );
}

function Sticker({ item, stickers }: { item: PanelSticker; stickers: PanelStickers }) {
  const { width, height, pad, icon } = stickers;
  const scale = icon.size / 24;
  return (
    <svg className={css.sticker} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${item.id}: ${item.title}`}>
      <title>{`${item.id}: ${item.title}`}</title>
      <rect className={css.card} x={0.05} y={0.05} width={width - 0.1} height={height - 0.1} rx={0.8} />
      <line className={css.rule} x1={pad} x2={width - pad} y1={stickers.rule_y} y2={stickers.rule_y} />
      <path className={css.text} d={item.text} />
      <g className={css.icon} transform={`translate(${icon.x} ${icon.y}) scale(${scale})`} strokeWidth={icon.stroke}>
        {(stickers.icons[item.icon] ?? []).map((d) => <path key={d} d={d} />)}
      </g>
    </svg>
  );
}
