import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DownloadMenu } from "./index";

describe("DownloadMenu", () => {
  it("offers the sheet PNG and the project DXF", async () => {
    const user = userEvent.setup();
    const onPng = vi.fn();
    render(<DownloadMenu onPng={onPng} dxf={{ href: "/api/projects/p1/out/project.dxf", name: "project.dxf" }} />);
    const button = screen.getByRole("button", { name: "Скачать" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    await user.click(button);
    expect(screen.getByRole("menuitem", { name: /Проект для AutoCAD/ })).toHaveAttribute("download", "project.dxf");
    await user.click(screen.getByRole("menuitem", { name: /Лист для альбома/ }));
    expect(onPng).toHaveBeenCalledOnce();
  });

  it("without a sheet or a build the items are off; the simple mode has no DXF", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<DownloadMenu onPng={null} dxf={null} />);
    await user.click(screen.getByRole("button", { name: "Скачать" }));
    expect(screen.getByRole("menuitem", { name: /Лист для альбома/ })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: /Проект не собран/ })).toBeDisabled();
    rerender(<DownloadMenu onPng={vi.fn()} dxf={null} withDxf={false} />);
    expect(screen.queryByRole("menuitem", { name: /DXF|AutoCAD|не собран/ })).toBeNull();
  });
});
