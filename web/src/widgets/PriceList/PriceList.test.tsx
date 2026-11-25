import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import { pricePage, priceRow } from "@/shared/testData";
import { PriceList } from "./index";

describe("PriceList", () => {
  it("shows each work with the studio price next to the market", async () => {
    const user = userEvent.setup();
    stubApi({ "GET /api/prices": pricePage() });
    render(<PriceList />);
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();
    const field = await screen.findByRole("textbox", { name: "Цена: Установка подрозетника" });
    expect(field).toHaveValue("100");
    const row = field.closest("tr")!;
    expect(within(row).getByText("120")).toBeInTheDocument();
    expect(within(row).getByRole("img", { name: "мин 80, медиана 120, макс 200" })).toBeInTheDocument();
    expect(within(row).getByText("-17%")).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "прайсов: 3" }));
    expect(screen.getByText("подрозетник в бетоне")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Мастер Сервис" })[0]).toHaveAttribute("href", "https://example.com/prices");
    expect(screen.getByText(/Рынок Киев: 1 открытых прайсов/)).toBeInTheDocument();
  });

  it("edits, refuses a wrong number, saves the changes and tells the page about unsaved ones", async () => {
    const user = userEvent.setup();
    const sent = stubApi({
      "GET /api/prices": pricePage(),
      "POST /api/prices": pricePage({ rows: [priceRow({ price: 120 })] }),
    });
    const onDirty = vi.fn();
    render(<PriceList onDirty={onDirty} />);
    const field = await screen.findByRole("textbox", { name: /Цена:/ });
    const save = screen.getByRole("button", { name: "Сохранить" });
    expect(save).toBeDisabled();
    await user.clear(field);
    await user.type(field, "-5");
    expect(screen.getByText("Цена — число не меньше 0")).toBeInTheDocument();
    expect(save).toBeDisabled();
    expect(onDirty).toHaveBeenLastCalledWith(true);
    await user.click(screen.getByRole("button", { name: "Поставить медиану рынка ценой студии" }));
    expect(field).toHaveValue("120");
    await user.click(save);
    expect(sent.at(-1)).toMatchObject({ method: "POST", body: { items: { "work.socket": 120 } } });
    expect(await screen.findByText("Сохранено в prices.yaml — сметы пересчитаются при сборке")).toBeInTheDocument();
    expect(onDirty).toHaveBeenLastCalledWith(false);
  });

  it("an empty field removes the price; reset drops the edits", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ "GET /api/prices": pricePage(), "POST /api/prices": pricePage() });
    render(<PriceList />);
    const field = await screen.findByRole("textbox", { name: /Цена:/ });
    await user.type(field, "5");
    await user.click(screen.getByRole("button", { name: "Сбросить" }));
    expect(field).toHaveValue("100");
    await user.clear(field);
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(sent.at(-1)?.body).toEqual({ items: { "work.socket": null } });
  });

  it("read-only without the right to edit; a row without market data says so", async () => {
    stubApi({ "GET /api/prices": pricePage({ editable: false, market: null, rows: [priceRow({ market: null, price: null, service: 90 })] }) });
    render(<PriceList />);
    expect(await screen.findByText("нет в прайсах")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Сохранить" })).toBeNull();
    expect(screen.getByText("в смете — имитация")).toBeInTheDocument();
  });

  it("shows materials in a table of their own, editable the same way", async () => {
    const user = userEvent.setup();
    const cable = priceRow({ key: "cable.3x1.5", kind: "material", section: "material_rough", unit: "м",
                             name: { ru: "Кабель ВВГнг 3×1,5", uk: "Кабель ВВГнг 3×1,5" }, price: 45, market: null });
    const box = priceRow({ key: "socket", kind: "material", section: "material_finish",
                           name: { ru: "Розетка", uk: "Розетка" }, price: null, service: 90, market: null });
    const sent = stubApi({ "GET /api/prices": pricePage({ rows: [priceRow({ kind: "work" }), cable, box] }),
                           "POST /api/prices": pricePage() });
    render(<PriceList />);
    const heading = await screen.findByRole("heading", { name: "Материалы" });
    const table = heading.nextElementSibling as HTMLElement;
    expect(within(table).getByRole("columnheader", { name: "Материал" })).toBeInTheDocument();
    expect(within(table).getByRole("textbox", { name: "Цена: Кабель ВВГнг 3×1,5" })).toHaveValue("45");
    expect(within(table).getByRole("textbox", { name: "Цена: Розетка" })).toHaveAttribute("placeholder", "90");
    expect(within(table).queryByText("нет в прайсах")).toBeNull();  // no market columns for materials
    await user.type(within(table).getByRole("textbox", { name: "Цена: Розетка" }), "60");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(sent.at(-1)?.body).toEqual({ items: { socket: 60 } });
  });

  it("the joint method of switch flush boxes: saved alone or with the prices; an older server means Wago", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ "GET /api/prices": pricePage(), "POST /api/prices": pricePage({ splice: "crimp" }) });
    const onDirty = vi.fn();
    render(<PriceList onDirty={onDirty} />);
    const group = await screen.findByRole("radiogroup", { name: "Соединения в подрозетниках выключателей" });
    expect(within(group).getByRole("radio", { name: "Клеммы Wago" })).toBeChecked();
    expect(screen.getByText(/Меняет работу «соединение в подрозетнике»/)).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Сохранить" });
    await user.click(within(group).getByRole("radio", { name: "Опрессовка" }));
    expect(onDirty).toHaveBeenLastCalledWith(true);
    await user.click(within(group).getByRole("radio", { name: "Клеммы Wago" }));  // back to the saved one
    expect(save).toBeDisabled();
    await user.click(within(group).getByRole("radio", { name: "Опрессовка" }));
    await user.click(save);
    expect(sent.at(-1)?.body).toEqual({ splice: "crimp" });
    expect(await screen.findByText("Сохранено в prices.yaml — сметы пересчитаются при сборке")).toBeInTheDocument();
    expect(within(group).getByRole("radio", { name: "Опрессовка" })).toBeChecked();
    // With a price edit — one request
    await user.click(within(group).getByRole("radio", { name: "Клеммы Wago" }));
    await user.type(screen.getByRole("textbox", { name: /Цена:/ }), "5");
    await user.click(save);
    expect(sent.at(-1)?.body).toEqual({ items: { "work.socket": 1005 }, splice: "wago" });
  });

  it("the joint method read-only without the right to edit", async () => {
    stubApi({ "GET /api/prices": pricePage({ editable: false, splice: "crimp" }) });
    render(<PriceList />);
    expect(await screen.findByText("Опрессовка")).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup")).toBeNull();
  });

  it("shows a load error", async () => {
    stubApi({ "GET /api/prices": fail(403, "Только студия") });
    render(<PriceList />);
    expect(await screen.findByRole("alert")).toHaveTextContent("403: Только студия");
  });
});
