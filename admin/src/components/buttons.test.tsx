import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Button, COPIED_MS, Confirm, CopyButton, IconButton, TIP_DELAY_MS } from "./buttons";
import { ICONS, Icon } from "./icons";

describe("Icon", () => {
  it("draws every icon as a hidden outline svg", () => {
    const { container } = render(<>{ICONS.map((n) => <Icon key={n} name={n} />)}</>);
    const svgs = container.querySelectorAll("svg");
    expect(svgs).toHaveLength(ICONS.length);
    svgs.forEach((svg) => {
      expect(svg).toHaveAttribute("aria-hidden", "true");
      expect(svg.querySelectorAll("path").length).toBeGreaterThan(0);
    });
  });
});

describe("IconButton", () => {
  it("is named by its label and shows it as a tooltip on keyboard focus, gone on blur", async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<><IconButton icon="ban" label="Отозвать" onClick={onClick} /><button>дальше</button></>);
    const button = screen.getByRole("button", { name: "Отозвать" });
    expect(button).toHaveAttribute("type", "button");
    expect(button).not.toHaveAttribute("title");  // the tooltip is ours, not the browser's
    await user.tab();
    expect(button).toHaveFocus();
    expect(document.querySelector("[data-tip]")).toHaveTextContent("Отозвать");
    await user.keyboard("{Enter}");
    expect(onClick).toHaveBeenCalledOnce();
    await user.tab();
    expect(document.querySelector("[data-tip]")).toBeNull();
  });

  it("shows the tooltip after a pause under the mouse, not under a finger", () => {
    vi.useFakeTimers();
    render(<IconButton icon="copy" label="Скопировать" />);
    const button = screen.getByRole("button", { name: "Скопировать" });
    fireEvent.pointerEnter(button, { pointerType: "touch" });
    act(() => { vi.advanceTimersByTime(TIP_DELAY_MS); });
    expect(document.querySelector("[data-tip]")).toBeNull();
    fireEvent.pointerEnter(button, { pointerType: "mouse" });
    act(() => { vi.advanceTimersByTime(TIP_DELAY_MS - 1); });
    expect(document.querySelector("[data-tip]")).toBeNull();
    act(() => { vi.advanceTimersByTime(1); });
    expect(document.querySelector("[data-tip]")).toHaveTextContent("Скопировать");
    fireEvent.pointerLeave(button);
    expect(document.querySelector("[data-tip]")).toBeNull();
  });
});

describe("Button", () => {
  it("is named by its text; the icon is decoration", () => {
    render(<Button icon="plus" variant="primary">Добавить</Button>);
    const button = screen.getByRole("button", { name: "Добавить" });
    expect(button.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});

describe("CopyButton", () => {
  it("copies, turns into a check named Скопировано, announces it and comes back", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(<CopyButton value="K7Q-2MX" />);
    const button = screen.getByRole("button", { name: "Скопировать" });
    expect(button.querySelector("[data-icon=copy]")).not.toBeNull();
    await user.click(button);
    expect(await navigator.clipboard.readText()).toBe("K7Q-2MX");
    // the same button, only the icon and the name change
    expect(button).toHaveAccessibleName("Скопировано");
    expect(button.querySelector("[data-icon=check]")).not.toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Скопировано");
    act(() => { vi.advanceTimersByTime(COPIED_MS); });
    expect(button).toHaveAccessibleName("Скопировать");
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });
});

describe("Confirm", () => {
  it("asks over the page: the button stays, focus goes to Нет; Нет closes, Да runs", async () => {
    const user = userEvent.setup();
    const onYes = vi.fn();
    render(<Confirm label="Убрать" icon="userMinus" question="Убрать Ивана?" onYes={onYes} />);
    const button = screen.getByRole("button", { name: "Убрать" });
    expect(button).toHaveAttribute("aria-expanded", "false");
    await user.click(button);
    const question = screen.getByRole("dialog", { name: "Убрать Ивана?" });
    expect(question).toHaveTextContent("Убрать Ивана?");
    expect(button).toHaveAttribute("aria-expanded", "true");
    expect(button).toHaveAttribute("aria-controls", question.id);
    expect(screen.getByRole("button", { name: "Нет" })).toHaveFocus();
    await user.click(screen.getByRole("button", { name: "Нет" }));
    expect(onYes).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(button).toHaveFocus();
    await user.click(button);
    await user.click(screen.getByRole("button", { name: "Да" }));
    expect(onYes).toHaveBeenCalledOnce();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes by Escape with focus back on the button, by a press outside and by a second press", async () => {
    const user = userEvent.setup();
    render(<><Confirm label="Отозвать" question="Отозвать код?" onYes={vi.fn()} /><p>снаружи</p></>);
    const button = screen.getByRole("button", { name: "Отозвать" });
    await user.click(button);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(button).toHaveFocus();
    await user.click(button);
    await user.click(screen.getByText("снаружи"));
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(button);
    await user.click(button);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("works from the keyboard and closes when Tab leaves it", async () => {
    const user = userEvent.setup();
    const onYes = vi.fn();
    render(<><Confirm label="Отозвать" question="Отозвать код?" onYes={onYes} /><button>дальше</button></>);
    await user.tab();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Нет" })).toHaveFocus();
    await user.tab();  // Нет → дальше: out of the question
    expect(screen.queryByRole("dialog")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Отозвать" }));
    await user.tab({ shift: true });  // Нет → Да
    await user.keyboard("{Enter}");
    expect(onYes).toHaveBeenCalledOnce();
  });

  it("with text shows the label next to the icon; a disabled action does not ask", () => {
    render(<Confirm text icon="lock" label="Заблокировать" question="?" onYes={() => {}} disabled />);
    const button = screen.getByRole("button", { name: "Заблокировать" });
    expect(button).toHaveTextContent("Заблокировать");
    expect(button).toBeDisabled();
  });
});
