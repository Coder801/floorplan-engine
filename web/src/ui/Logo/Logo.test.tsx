import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Logo } from "./index";

describe("Logo", () => {
  it("is the St mark of the given height, wider than tall, hidden from screen readers", () => {
    const { container } = render(<Logo size={32} />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveTextContent("St");
    expect(svg).toHaveAttribute("height", "32");
    expect(svg).toHaveAttribute("width", "36");
    expect(svg).toHaveAttribute("aria-hidden", "true");
  });
});
