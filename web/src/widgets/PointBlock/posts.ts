// Posts of a frame, left to right: one entry per post with its kind and whether it belongs to the
// point the hint is about. A build without `items` knows only the posts of that point: all sockets

import type { PointBlock } from "@/shared/types";

export interface FramePost {
  type: string;
  own: boolean;
}

export function framePosts(block: PointBlock): FramePost[] {
  const items = block.items?.length ? block.items : [{ type: "socket", posts: block.posts, own: true }];
  return items.flatMap((it) => Array.from({ length: Math.max(1, it.posts) }, () => ({ type: it.type, own: it.own })));
}
