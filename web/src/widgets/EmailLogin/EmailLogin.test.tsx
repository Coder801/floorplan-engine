import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import { EmailLogin } from "./index";

describe("EmailLogin", () => {
  it("sends a code to the address and logs in when the code is typed", async () => {
    const user = userEvent.setup();
    const sent = stubApi({
      "POST /api/auth/email/start": { sent: true, resend_in: 0 },
      "POST /api/auth/email/verify": { ok: true, invite_error: null },
    });
    const onDone = vi.fn();
    render(<EmailLogin onDone={onDone} />);
    const get = screen.getByRole("button", { name: "Получить код" });
    expect(get).toBeDisabled();
    await user.type(screen.getByRole("textbox", { name: "Почта" }), "ivan@example.com");
    await user.click(get);
    expect(sent[0]).toMatchObject({ method: "POST", body: { email: "ivan@example.com", lang: "ru" } });
    expect(await screen.findByText(/Код отправлен на ivan@example.com/)).toBeInTheDocument();
    const code = screen.getByRole("textbox", { name: "Код из письма" });
    await user.type(code, "12a34-5");
    expect(code).toHaveValue("12345");
    expect(screen.getByRole("button", { name: "Войти" })).toBeDisabled();
    await user.type(code, "6");
    expect(sent.at(-1)).toMatchObject({ path: "/api/auth/email/verify", body: { email: "ivan@example.com", code: "123456" } });
    await vi.waitFor(() => expect(onDone).toHaveBeenCalledOnce());
  });

  it("shows a wrong code and lets the address be changed", async () => {
    const user = userEvent.setup();
    stubApi({
      "POST /api/auth/email/start": { sent: true, resend_in: 0 },
      "POST /api/auth/email/verify": fail(400, "Неверный код"),
    });
    const onDone = vi.fn();
    render(<EmailLogin onDone={onDone} />);
    await user.type(screen.getByRole("textbox", { name: "Почта" }), "ivan@example.com{Enter}");
    await user.type(await screen.findByRole("textbox", { name: "Код из письма" }), "000000");
    expect(await screen.findByRole("alert")).toHaveTextContent("Неверный код");
    expect(onDone).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Другая почта" }));
    expect(screen.getByRole("textbox", { name: "Почта" })).toHaveValue("ivan@example.com");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("counts down before the code can be sent again", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const sent = stubApi({ "POST /api/auth/email/start": { sent: true, resend_in: 2 } });
    render(<EmailLogin onDone={vi.fn()} />);
    await user.type(screen.getByRole("textbox", { name: "Почта" }), "a@b.c{Enter}");
    expect(await screen.findByRole("button", { name: "Ещё раз — через 2 с" })).toBeDisabled();
    await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(screen.getByRole("button", { name: "Ещё раз — через 1 с" })).toBeDisabled();
    await act(() => vi.advanceTimersByTimeAsync(1000));
    await user.click(screen.getByRole("button", { name: "Отправить ещё раз" }));
    expect(sent.filter((r) => r.path === "/api/auth/email/start")).toHaveLength(2);
  });

  it("shows a refusal to send", async () => {
    const user = userEvent.setup();
    stubApi({ "POST /api/auth/email/start": fail(429, "Слишком часто") });
    render(<EmailLogin onDone={vi.fn()} />);
    await user.type(screen.getByRole("textbox", { name: "Почта" }), "a@b.c{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Слишком часто");
    expect(screen.getByRole("textbox", { name: "Почта" })).toBeInTheDocument();
  });
});
