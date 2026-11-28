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
    expect(field).toHaveValue("100,00");
    const row = field.closest("tr")!;
    expect(within(row).getByText("120,00")).toBeInTheDocument();
    expect(within(row).getByRole("img", { name: "мин 80,00, медиана 120,00, макс 200,00" })).toBeInTheDocument();
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
    expect(field).toHaveValue("120,00");
    await user.click(save);
    expect(sent.at(-1)).toMatchObject({ method: "POST", body: { items: { "work.socket": 120 } } });
    expect(await screen.findByText("Сохранено в прайсе студии — сметы пересчитаются при сборке")).toBeInTheDocument();
    expect(onDirty).toHaveBeenLastCalledWith(false);
  });

  it("a price is typed with a comma or a dot, shown back with kopecks and saved rounded to them", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ "GET /api/prices": pricePage(), "POST /api/prices": pricePage() });
    const onDirty = vi.fn();
    render(<PriceList onDirty={onDirty} />);
    const field = await screen.findByRole("textbox", { name: /Цена:/ });
    await user.clear(field);
    await user.type(field, "100");
    await user.tab();
    expect(field).toHaveValue("100,00");
    expect(onDirty).toHaveBeenLastCalledWith(false);  // the saved price typed again is no change
    await user.clear(field);
    await user.type(field, "76.505");
    await user.tab();
    expect(field).toHaveValue("76,51");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(sent.at(-1)?.body).toEqual({ items: { "work.socket": 76.51 } });
  });

  it("an empty field removes the price; reset drops the edits", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ "GET /api/prices": pricePage(), "POST /api/prices": pricePage() });
    render(<PriceList />);
    const field = await screen.findByRole("textbox", { name: /Цена:/ });
    await user.type(field, "5");
    await user.click(screen.getByRole("button", { name: "Сбросить" }));
    expect(field).toHaveValue("100,00");
    await user.clear(field);
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(sent.at(-1)?.body).toEqual({ items: { "work.socket": null } });
  });

  it("read-only without the right to edit; a row without market data says so; no mock price", async () => {
    stubApi({ "GET /api/prices": pricePage({ editable: false, market: null, rows: [priceRow({ market: null, price: null })] }) });
    render(<PriceList />);
    expect(await screen.findByText("нет в прайсах")).toBeInTheDocument();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Сохранить" })).toBeNull();
    expect(screen.queryByText(/имитаци/)).toBeNull();
  });

  it("finish material prices the list still holds are reported as dropped on save", async () => {
    stubApi({ "GET /api/prices": pricePage({ stale: ["socket", "breaker"] }) });
    render(<PriceList />);
    expect(await screen.findByText(/Цены чистовых материалов \(2 поз\.\) больше не учитываются/)).toBeInTheDocument();
  });

  it("shows materials in a table of their own, editable the same way", async () => {
    const user = userEvent.setup();
    const cable = priceRow({ key: "cable.3x1.5", kind: "material", section: "material_rough", unit: "м",
                             name: { ru: "Кабель ВВГнг 3×1,5", uk: "Кабель ВВГнг 3×1,5" }, price: 45, market: null });
    const box = priceRow({ key: "socket_box", kind: "material", section: "material_rough",
                           name: { ru: "Подрозетник", uk: "Підрозетник" }, price: null, market: null });
    const sent = stubApi({ "GET /api/prices": pricePage({ rows: [priceRow({ kind: "work" }), cable, box] }),
                           "POST /api/prices": pricePage() });
    render(<PriceList />);
    const heading = await screen.findByRole("heading", { name: "Материалы" });
    const table = heading.nextElementSibling as HTMLElement;
    expect(within(table).getByRole("columnheader", { name: "Материал" })).toBeInTheDocument();
    expect(within(table).getByRole("textbox", { name: "Цена: Кабель ВВГнг 3×1,5" })).toHaveValue("45,00");
    expect(within(table).getByRole("textbox", { name: "Цена: Подрозетник" })).toHaveAttribute("placeholder", "—");
    expect(within(table).queryByText("нет в прайсах")).toBeNull();  // no market columns for materials
    await user.type(within(table).getByRole("textbox", { name: "Цена: Подрозетник" }), "20");
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(sent.at(-1)?.body).toEqual({ items: { socket_box: 20 } });
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
    expect(await screen.findByText("Сохранено в прайсе студии — сметы пересчитаются при сборке")).toBeInTheDocument();
    expect(within(group).getByRole("radio", { name: "Опрессовка" })).toBeChecked();
    // With a price edit — one request
    await user.click(within(group).getByRole("radio", { name: "Клеммы Wago" }));
    await user.clear(screen.getByRole("textbox", { name: /Цена:/ }));
    await user.type(screen.getByRole("textbox", { name: /Цена:/ }), "1005");
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
