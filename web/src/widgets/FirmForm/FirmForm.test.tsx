import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import { FirmForm } from "./index";

describe("FirmForm", () => {
  it("asks for the kind, then registers the firm", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ "POST /api/auth/firm": { id: "u1" } });
    const onDone = vi.fn();
    render(<FirmForm onBack={vi.fn()} onDone={onDone} />);
    const submit = screen.getByRole("button", { name: "Зарегистрировать" });
    expect(submit).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Название фирмы" }), "Искра");
    await user.click(submit);
    expect(screen.getByRole("alert")).toHaveTextContent("Выберите, чем занимается фирма.");
    expect(sent).toHaveLength(0);
    await user.click(screen.getByRole("radio", { name: /Электромонтаж/ }));
    await user.type(screen.getByRole("textbox", { name: /Город/ }), "Киев");
    await user.click(submit);
    expect(sent[0].body).toEqual({ name: "Искра", business: "electric", city: "Киев", phone: "" });
    await vi.waitFor(() => expect(onDone).toHaveBeenCalledOnce());
  });

  it("shows a refusal; back returns", async () => {
    const user = userEvent.setup();
    stubApi({ "POST /api/auth/firm": fail(409, "У вас уже есть фирма") });
    const onBack = vi.fn();
    render(<FirmForm onBack={onBack} onDone={vi.fn()} />);
    await user.type(screen.getByRole("textbox", { name: "Название фирмы" }), "Искра");
    await user.click(screen.getByRole("radio", { name: /Частный мастер/ }));
    await user.click(screen.getByRole("button", { name: "Зарегистрировать" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("У вас уже есть фирма");
    await user.click(screen.getByRole("button", { name: "Назад" }));
    expect(onBack).toHaveBeenCalledOnce();
  });
});
