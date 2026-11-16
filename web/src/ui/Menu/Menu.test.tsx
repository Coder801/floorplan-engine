import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Menu } from "./index";

describe("Menu", () => {
  it("is a named menu with its items", () => {
    render(<Menu label="Скачать"><button role="menuitem">PNG</button><button role="menuitem">DXF</button></Menu>);
    const menu = screen.getByRole("menu", { name: "Скачать" });
    expect(menu).toContainElement(screen.getByRole("menuitem", { name: "PNG" }));
    expect(menu).toContainElement(screen.getByRole("menuitem", { name: "DXF" }));
  });

  it("takes another role (a listbox)", () => {
    render(<Menu role="listbox" label="Язык"><button role="option" aria-selected>Русский</button></Menu>);
    expect(screen.getByRole("listbox", { name: "Язык" })).toBeInTheDocument();
  });
});
