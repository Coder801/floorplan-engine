// Whether this browser has already seen the notice about the product stage. The key holds the
// stage, so a new stage (beta) shows its own notice once again
import { remember, remembered } from "@/shared/palette";

export const noticeKey = (stage: string) => `notice:${stage}`;
export const noticeSeen = (stage: string) => remembered(noticeKey(stage)) === "seen";
export const markNoticeSeen = (stage: string) => remember(noticeKey(stage), "seen");
