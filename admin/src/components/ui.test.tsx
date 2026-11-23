import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Cols, Dialog, ErrorLine, Section, Segmented, Status, W, useAction, useLoad } from "./ui";

describe("Status", () => {
  it("says the state in words, or the given label", () => {
    render(<><Status state="revoked" /><Status state="active" label="активен" /><Status state="odd" /></>);
    expect(screen.getByText("отозван")).toBeInTheDocument();
    expect(screen.getByText("активен")).toBeInTheDocument();
    expect(screen.getByText("odd")).toBeInTheDocument();
  });
});

describe("ErrorLine", () => {
  it("announces an error and shows nothing without one", () => {
    const { rerender } = render(<ErrorLine error="последний владелец" />);
    expect(screen.getByRole("alert")).toHaveTextContent("последний владелец");
    rerender(<ErrorLine error={null} />);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("Cols", () => {
  it("gives the columns their widths, null takes the rest", () => {
    const { container } = render(<table><Cols w={[null, W.day, W.act]} /><tbody><tr><td>a</td><td>b</td><td>c</td></tr></tbody></table>);
    const cols = container.querySelectorAll("col");
    expect(cols).toHaveLength(3);
    expect(cols[0].getAttribute("style")).toBeNull();
    expect(cols[1]).toHaveStyle({ width: `${W.day}px` });
    expect(cols[2]).toHaveStyle({ width: `${W.act}px` });
  });
});

describe("Dialog", () => {
  it("is a named dialog closed by ×, Esc and a press on the backdrop, not inside", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(<Dialog title="Код доступа" onClose={onClose}><p>внутри</p></Dialog>);
    const dialog = screen.getByRole("dialog", { name: "Код доступа" });
    fireEvent.mouseDown(screen.getByText("внутри"));
    expect(onClose).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Закрыть" }));
    await user.keyboard("{Escape}");
    fireEvent.mouseDown(dialog.parentElement!);
    expect(onClose).toHaveBeenCalledTimes(3);
  });
});

describe("Section", () => {
  it("shows the title, its action and the content", () => {
    render(<Section title="Участники (2)" action={<button>+ Добавить</button>}><p>список</p></Section>);
    expect(screen.getByText("Участники (2)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ Добавить" })).toBeInTheDocument();
    expect(screen.getByText("список")).toBeInTheDocument();
  });
});

describe("Segmented", () => {
  it("shows the options by their labels and passes the clicked one", async () => {
    const onChange = vi.fn();
    render(<Segmented options={["owner", "designer"]} value="owner" onChange={onChange} label={(v) => v.toUpperCase()} />);
    await userEvent.click(screen.getByRole("button", { name: "DESIGNER" }));
    expect(onChange).toHaveBeenCalledWith("designer");
  });
});

function Loaded({ fetcher }: { fetcher: () => Promise<string> }) {
  const load = useLoad(fetcher, []);
  return (
    <>
      <span>{load.data ?? "пусто"}</span>
      <ErrorLine error={load.error} />
      <button onClick={load.reload}>Обновить</button>
      <button onClick={() => load.set("вручную")}>Заменить</button>
    </>
  );
}

describe("useLoad", () => {
  it("shows the data, reloads it and takes a fresh answer", async () => {
    const user = userEvent.setup();
    const fetcher = vi.fn().mockResolvedValueOnce("первый").mockResolvedValueOnce("второй");
    render(<Loaded fetcher={fetcher} />);
    expect(await screen.findByText("первый")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Обновить" }));
    expect(await screen.findByText("второй")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Заменить" }));
    expect(screen.getByText("вручную")).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it("shows the error of a failed request", async () => {
    render(<Loaded fetcher={() => Promise.reject(new Error("нет доступа"))} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("нет доступа");
  });
});

function Acting({ fn, onDone }: { fn: () => Promise<string>; onDone: (v: string) => void }) {
  const action = useAction();
  return (
    <>
      <button disabled={action.busy} onClick={() => action.run(fn, onDone)}>Сделать</button>
      <button onClick={action.clear}>Сбросить</button>
      <ErrorLine error={action.error} />
    </>
  );
}

describe("useAction", () => {
  it("passes the result on success", async () => {
    const onDone = vi.fn();
    render(<Acting fn={() => Promise.resolve("ok")} onDone={onDone} />);
    await userEvent.click(screen.getByRole("button", { name: "Сделать" }));
    expect(onDone).toHaveBeenCalledWith("ok");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the reason of a failure next to the action until cleared", async () => {
    const user = userEvent.setup();
    const onDone = vi.fn();
    render(<Acting fn={() => Promise.reject(new Error("у студии остаётся владелец"))} onDone={onDone} />);
    await user.click(screen.getByRole("button", { name: "Сделать" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("у студии остаётся владелец");
    expect(onDone).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Сделать" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Сбросить" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
