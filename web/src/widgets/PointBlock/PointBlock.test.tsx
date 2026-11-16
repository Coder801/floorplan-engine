import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PointBlock } from "./index";

describe("PointBlock", () => {
  it("draws the frame with its posts and says where it stands", () => {
    const { container } = render(<PointBlock block={{ posts: 3, x: 400, y: 300, wall: "w1", items: [
      { type: "socket", posts: 1, own: true }, { type: "pass_switch", posts: 1, own: false }, { type: "tv", posts: 1, own: false },
    ] }} />);
    expect(screen.getByRole("img", { name: "Блок: постов 3, 400 мм от начала стены, 300 мм от пола" })).toBeInTheDocument();
    expect(screen.getByText("TV")).toBeInTheDocument();
    expect(screen.getByText("400 мм")).toBeInTheDocument();
    expect(container.querySelectorAll("circle")).toHaveLength(1);
  });
});
