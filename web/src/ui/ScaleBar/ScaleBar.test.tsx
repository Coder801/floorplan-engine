import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { rulerLength } from "@/shared/zoom";
import { ScaleBar } from "./index";

describe("ScaleBar", () => {
  it("shows a round length at the current zoom", () => {
    const { label } = rulerLength(0.1);
    const { container } = render(<ScaleBar zoom={{ step: 0, label: "100%", pxPerMm: 0.1 }} />);
    expect(screen.getByLabelText(`Линейка: ${label}`)).toBeInTheDocument();
    expect(container).toHaveTextContent(label);
  });

  it("is not drawn without a scale", () => {
    const { container } = render(<ScaleBar zoom={{ step: 0, label: "100%", pxPerMm: null }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
