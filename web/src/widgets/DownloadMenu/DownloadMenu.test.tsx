import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DownloadMenu, FILES_PAUSED } from "./index";

describe("DownloadMenu", () => {
  it.runIf(FILES_PAUSED)("sheet PNG and DXF are paused: shown off, with a note", async () => {
    const user = userEvent.setup();
    const onPng = vi.fn();
    render(<DownloadMenu onPng={onPng} dxf={{ href: "/api/projects/p1/out/project.dxf", name: "project.dxf" }} />);
    await user.click(screen.getByRole("button", { name: "Скачать" }));
    const png = screen.getByRole("menuitem", { name: /Лист для альбома/ });
    const dxf = screen.getByRole("menuitem", { name: /Проект для AutoCAD/ });
    expect(png).toBeDisabled();
    expect(dxf).toBeDisabled();
    expect(dxf).not.toHaveAttribute("download");
    expect(png).toHaveTextContent("Временно недоступно");
    await user.click(png);
    expect(onPng).not.toHaveBeenCalled();
  });

  it("the simple mode has no DXF item", async () => {
    const user = userEvent.setup();
    render(<DownloadMenu onPng={vi.fn()} dxf={null} withDxf={false} />);
    await user.click(screen.getByRole("button", { name: "Скачать" }));
    expect(screen.queryByRole("menuitem", { name: /DXF|AutoCAD|не собран/ })).toBeNull();
  });

  it.skipIf(FILES_PAUSED)("offers the sheet PNG and the project DXF", async () => {
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

  it.skipIf(FILES_PAUSED)("without a sheet or a build the items are off; the simple mode has no DXF", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<DownloadMenu onPng={null} dxf={null} />);
    await user.click(screen.getByRole("button", { name: "Скачать" }));
    expect(screen.getByRole("menuitem", { name: /Лист для альбома/ })).toBeDisabled();
    expect(screen.getByRole("menuitem", { name: /Проект не собран/ })).toBeDisabled();
    rerender(<DownloadMenu onPng={vi.fn()} dxf={null} withDxf={false} />);
    expect(screen.queryByRole("menuitem", { name: /DXF|AutoCAD|не собран/ })).toBeNull();
  });

  it("the estimate for print opens its dialog; off without a build, gone without electrical", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<DownloadMenu onPng={null} dxf={null} withDxf={false} report="p1" />);
    await user.click(screen.getByRole("button", { name: "Скачать" }));
    await user.click(screen.getByRole("menuitem", { name: /Смета для печати/ }));
    expect(screen.getByRole("dialog", { name: "Смета для печати" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Отмена" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    rerender(<DownloadMenu onPng={null} dxf={null} report={null} />);
    await user.click(screen.getByRole("button", { name: "Скачать" }));
    expect(screen.getByRole("menuitem", { name: /Смета для печати/ })).toBeDisabled();
    rerender(<DownloadMenu onPng={null} dxf={null} />);
    expect(screen.queryByRole("menuitem", { name: /Смета для печати/ })).toBeNull();
  });
});
