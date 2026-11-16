import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Tag } from "./index";

describe("Tag", () => {
  it("shows the label with its hint", () => {
    render(<Tag variant="mono" title="Формат файла">DXF</Tag>);
    expect(screen.getByText("DXF")).toHaveAttribute("title", "Формат файла");
  });
});
