import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RebuildModal } from "./index";

describe("RebuildModal", () => {
  it("blocks the page with a busy alert dialog while the project rebuilds", () => {
    render(<RebuildModal />);
    const dialog = screen.getByRole("alertdialog", { name: "Пересчитываю смету…" });
    expect(dialog).toHaveAttribute("aria-busy", "true");
    expect(dialog).toHaveTextContent("Проект пересобирается");
  });
});
