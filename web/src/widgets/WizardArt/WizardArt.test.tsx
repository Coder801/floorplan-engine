import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ART, WizardArt } from "./index";

describe("WizardArt", () => {
  it("draws the picture of a card, hidden from screen readers (the card says it in words)", () => {
    const { container, rerender } = render(<WizardArt name="route-ceiling" />);
    const svg = container.querySelector("svg")!;
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg.childElementCount).toBeGreaterThan(0);
    rerender(<WizardArt name="no-such-card" />);
    expect(container.querySelector("svg")!.childElementCount).toBe(0);  // an empty frame, not a broken card
  });

  it("every picture renders", () => {
    for (const name of Object.keys(ART)) {
      const { container, unmount } = render(<WizardArt name={name} />);
      expect(container.querySelector("svg")).not.toBeNull();
      unmount();
    }
  });
});
