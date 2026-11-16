import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Icon } from "./index";

describe("Icon", () => {
  it("draws the named icon, hidden from screen readers (the label says it)", () => {
    const { container } = render(<Icon name="door" />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg.querySelectorAll("path")).toHaveLength(3);
  });
});
