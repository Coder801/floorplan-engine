import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { WorkStatusBadge } from "./index";

describe("WorkStatusBadge", () => {
  it("names the status", () => {
    render(<WorkStatusBadge status="review" big />);
    expect(screen.getByText("На приёмке")).toBeInTheDocument();
  });
});
