import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { PanelSticker, PanelStickers } from "@/shared/types";
import { StickersStage } from "./index";

const sticker = (over: Partial<PanelSticker>): PanelSticker => ({
  id: "QF1", row: 0, title: "Свет", icon: "light", number: "M0 0", name: "M1 1", short_id: "1", short_number: "M2 2",
  color: "#d00000", on_color: "#ffffff", ...over,
});

const stickers: PanelStickers = {
  width: 18, height: 12, pad: 1, rule_y: 6, band: "M0 0H18V4H0Z", icon: { x: 1, y: 1, size: 4, stroke: 0.3 },
  items: [sticker({}), sticker({ id: "QF2", title: "Розетки", short_id: "2" }), sticker({ id: "QS1", row: 1, title: "Ввод", short_id: "QS1" })],
  icons: { light: ["M0 0L24 24"] },
};

describe("StickersStage", () => {
  it("lays the stickers rail by rail and offers the PDF of the chosen style", async () => {
    const user = userEvent.setup();
    const file = vi.fn((colored: boolean, short: boolean) => `/out/stickers-${colored ? "color" : "black"}${short ? "-short" : ""}.pdf`);
    render(<StickersStage stickers={stickers} file={file} />);
    expect(screen.getByText("3 шт. · 18 × 12 мм · печатать в масштабе 100 %")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Рейка 1" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Рейка 2" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "QF2: Розетки" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Скачать PDF" })).toHaveAttribute("href", "/out/stickers-black.pdf");
    await user.click(screen.getByRole("radio", { name: "Только цифры" }));
    expect(screen.getByRole("img", { name: "2: Розетки" })).toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "Цветная" }));
    expect(screen.getByRole("link", { name: "Скачать PDF" })).toHaveAttribute("href", "/out/stickers-color-short.pdf");
  });

  it("no PDF in the build, no button", () => {
    render(<StickersStage stickers={stickers} file={() => null} />);
    expect(screen.queryByRole("link")).toBeNull();
  });
});
