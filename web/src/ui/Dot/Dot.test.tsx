import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Dot } from "./index";

describe("Dot", () => {
  it("is decoration in the group colour; without a colour it takes the muted one from the styles", () => {
    const { container, rerender } = render(<Dot color="#e63c00" />);
    const dot = container.firstElementChild!;
    expect(dot).toHaveAttribute("aria-hidden", "true");
    expect(dot).toHaveStyle({ background: "#e63c00" });
    rerender(<Dot shape="square" />);
    expect((container.firstElementChild as HTMLElement).style.background).toBe("");
  });
});
