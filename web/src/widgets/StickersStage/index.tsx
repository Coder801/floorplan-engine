// Stickers of the panel: rail by rail, as they go on the devices. Geometry comes ready from the
// core (sheets/stickers.py, key panel.stickers), the same as in the PDF out/panel-stickers.pdf.

import { useState } from "react";
import { useTranslation } from "react-i18next";
import { cx } from "@/shared/cx";
import ui from "@/shared/styles/ui.module.scss";
import type { PanelSticker, PanelStickers } from "@/shared/types";
import css from "./StickersStage.module.scss";

export type StickerFile = (colored: boolean, short: boolean) => string | null;  // PDF of the build

interface Props {
  stickers: PanelStickers;
  file: StickerFile;
}

export function StickersStage({ stickers, file }: Props) {
  const { t } = useTranslation();
  const [colored, setColored] = useState(false);
  const [short, setShort] = useState(false);
  const pdf = file(colored, short);
  const rails = [...new Set(stickers.items.map((s) => s.row))];
  return (
    <div className={css.stage}>
      <article className={css.sheet}>
        <header className={css.head}>
          <div>
            <h1>{t("panel.stickers")}</h1>
            <p>{t("panel.stickersNote", { n: stickers.items.length, width: stickers.width, height: stickers.height })}</p>
          </div>
          <div className={css.actions}>
            <div className={ui.segmented} role="group" aria-label={t("panel.stickersNumber")}>
              <button className={cx(!short && ui.on)} aria-pressed={!short} onClick={() => setShort(false)}>{t("panel.stickersFull")}</button>
              <button className={cx(short && ui.on)} aria-pressed={short} onClick={() => setShort(true)}>{t("panel.stickersShort")}</button>
            </div>
            <div className={ui.segmented} role="group" aria-label={t("panel.stickersStyle")}>
              <button className={cx(!colored && ui.on)} aria-pressed={!colored} onClick={() => setColored(false)}>{t("panel.stickersBlack")}</button>
              <button className={cx(colored && ui.on)} aria-pressed={colored} onClick={() => setColored(true)}>{t("panel.stickersColor")}</button>
            </div>
            {pdf && <a className={css.pdf} href={pdf} download>{t("panel.stickersPdf")}</a>}
          </div>
        </header>
        {rails.map((row, i) => (
          <section key={row}>
            <h2>{t("panel.rail", { n: i + 1 })}</h2>
            <div className={css.rail}>
              {stickers.items.filter((s) => s.row === row).map((s) => <Sticker key={s.id} item={s} stickers={stickers} colored={colored} short={short} />)}
            </div>
          </section>
        ))}
      </article>
    </div>
  );
}

function Sticker({ item, stickers, colored, short }: { item: PanelSticker; stickers: PanelStickers; colored: boolean; short: boolean }) {
  const { width, height, pad, icon } = stickers;
  const scale = icon.size / 24;
  const title = `${short ? item.short_id : item.id}: ${item.title}`;
  return (
    <svg className={css.sticker} viewBox={`0 0 ${width} ${height}`} role="img" aria-label={title}>
      <title>{title}</title>
      <rect className={css.card} x={0.05} y={0.05} width={width - 0.1} height={height - 0.1} rx={0.8} />
      {colored
        ? <path d={stickers.band} fill={item.color} />
        : <line className={css.rule} x1={pad} x2={width - pad} y1={stickers.rule_y} y2={stickers.rule_y} />}
      <path d={short ? item.short_number : item.number} fill={colored ? item.on_color : "#000"} />
      <path d={item.name} fill="#000" />
      <g className={css.icon} transform={`translate(${icon.x} ${icon.y}) scale(${scale})`}
         strokeWidth={icon.stroke} stroke={colored ? item.color : "#000"}>
        {(stickers.icons[item.icon] ?? []).map((d) => <path key={d} d={d} />)}
      </g>
    </svg>
  );
}
