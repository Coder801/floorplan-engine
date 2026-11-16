import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StepMark } from "./index";

describe("StepMark", () => {
  it("with a label it is an image for screen readers", () => {
    render(<StepMark done label="Решено" />);
    expect(screen.getByRole("img", { name: "Решено" })).toBeInTheDocument();
  });

  it("without a label it is decoration", () => {
    render(<StepMark done={false} />);
    expect(screen.queryByRole("img")).toBeNull();
  });
});
