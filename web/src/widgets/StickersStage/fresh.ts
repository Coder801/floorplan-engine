// Only a build of the current format can be drawn: an .epd of an earlier one has its stickers
// without curves and colours, they would come out blank. Such a build has no switch until rebuilt.

import type { PanelStickers } from "@/shared/types";

export const freshStickers = (stickers?: PanelStickers): PanelStickers | undefined =>
  stickers?.items.every((s) => s.short_number && s.name !== undefined && s.color) ? stickers : undefined;
