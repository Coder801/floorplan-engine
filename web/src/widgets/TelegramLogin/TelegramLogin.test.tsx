import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import { TelegramLogin } from "./index";

const TICKET = { token: "t1", url: "https://t.me/bot?start=t1", expires_in: 300 };

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  vi.stubGlobal("open", vi.fn());
});

const setup = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime });

// The poll timer is set only after the start request has answered, and every answer is parsed
// asynchronously (Response.json): a click or a timer step may return before that, all the more so
// under the load of a full run. So fake time is advanced only after the waiting screen is on
// (findByRole "status"), and the result of a poll is awaited, not read right after the step.
// A step until the condition holds: each one fires the next poll if it is already scheduled.
const pollUntil = (check: () => void) => vi.waitFor(async () => {
  await act(() => vi.advanceTimersByTimeAsync(2000));
  check();
});

describe("TelegramLogin", () => {
  it("opens the bot, polls the ticket with the invite and logs in", async () => {
    const user = setup();
    let polls = 0;
    let doneAt = 0;
    const sent = stubApi({
      "POST /api/auth/telegram/start": TICKET,
      "GET /api/auth/telegram/status": () => ({ status: ++polls < 2 ? "pending" : "done" }),
    });
    const onDone = vi.fn(() => { doneAt = polls; });
    render(<TelegramLogin onDone={onDone} invite="inv" />);
    await user.click(screen.getByRole("button", { name: "Войти через Telegram" }));
    expect(window.open).toHaveBeenCalledWith(TICKET.url, "_blank", "noopener");
    expect(await screen.findByRole("status")).toHaveTextContent("Откройте Telegram");
    expect(screen.getByRole("link", { name: "Открыть Telegram ещё раз" })).toHaveAttribute("href", TICKET.url);
    await pollUntil(() => expect(onDone).toHaveBeenCalled());
    expect(onDone).toHaveBeenCalledOnce();
    expect(doneAt).toBe(2);  // the "pending" poll did not log in, the next one did
    expect(sent.at(-1)?.path).toBe("/api/auth/telegram/status?token=t1&invite=inv");
  });

  it("an expired ticket goes back to the button with an explanation", async () => {
    const user = setup();
    stubApi({ "POST /api/auth/telegram/start": TICKET, "GET /api/auth/telegram/status": fail(410, "истёк") });
    render(<TelegramLogin onDone={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Войти через Telegram" }));
    await screen.findByRole("status");
    await pollUntil(() => expect(screen.getByRole("alert")).toHaveTextContent("Ссылка устарела — попробуйте ещё раз."));
    expect(screen.getByRole("button", { name: "Войти через Telegram" })).toBeEnabled();
  });

  it("cancel stops waiting", async () => {
    const user = setup();
    const sent = stubApi({ "POST /api/auth/telegram/start": TICKET });
    render(<TelegramLogin onDone={vi.fn()} />);
    await user.click(screen.getByRole("button", { name: "Войти через Telegram" }));
    await user.click(await screen.findByRole("button", { name: "Отмена" }));
    await act(() => vi.advanceTimersByTimeAsync(4000));
    expect(sent).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Войти через Telegram" })).toBeInTheDocument();
  });
});
