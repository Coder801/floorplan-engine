import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MarkLoader } from "./index";

describe("MarkLoader", () => {
  it("is the St mark of the given height, hidden from screen readers (the caller says what loads)", () => {
    const { container } = render(<MarkLoader size={64} />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveTextContent("St");
    expect(svg).toHaveAttribute("height", "64");
    expect(svg).toHaveAttribute("width", "72");
    expect(svg).toHaveAttribute("aria-hidden", "true");
  });
});
