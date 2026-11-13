import { describe, expect, it } from "vitest";
import { framePosts } from "./posts";

const base = { x: 1200, y: 300, wall: "elevation:r.w1" };

describe("framePosts", () => {
  it("lists every post of the frame and marks the chosen point", () => {
    const posts = framePosts({
      ...base, posts: 4,
      items: [
        { type: "socket", posts: 2, own: false },
        { type: "switch", posts: 1, own: false },
        { type: "data", posts: 1, own: true },
      ],
    });
    expect(posts.map((p) => p.type)).toEqual(["socket", "socket", "switch", "data"]);
    expect(posts.map((p) => p.own)).toEqual([false, false, false, true]);
  });

  it("draws an older build as sockets of the point itself", () => {
    expect(framePosts({ ...base, posts: 3 })).toEqual(Array(3).fill({ type: "socket", own: true }));
  });
});
