import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fail, stubApi } from "@/shared/testApi";
import { CodeLogin } from "./index";

describe("CodeLogin", () => {
  it("formats the code as typed and opens the code's project", async () => {
    const user = userEvent.setup();
    const sent = stubApi({ "POST /api/auth/code": { ok: true, project: "p1" } });
    const onDone = vi.fn();
    render(<CodeLogin onDone={onDone} />);
    const field = screen.getByRole("textbox", { name: "Код от студии" });
    const open = screen.getByRole("button", { name: "Открыть проект" });
    await user.type(field, "k7q2");
    expect(open).toBeDisabled();
    await user.type(field, "mxab");
    expect(field).toHaveValue("K7Q2-MXAB");
    await user.click(open);
    expect(sent[0].body).toEqual({ code: "K7Q2-MXAB" });
    await vi.waitFor(() => expect(onDone).toHaveBeenCalledWith("p1"));
  });

  it("shows the server's reason for a wrong code", async () => {
    const user = userEvent.setup();
    stubApi({ "POST /api/auth/code": fail(403, "Код истёк") });
    const onDone = vi.fn();
    render(<CodeLogin onDone={onDone} />);
    await user.type(screen.getByRole("textbox", { name: "Код от студии" }), "K7Q2MXAB{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent("Код истёк");
    expect(onDone).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Открыть проект" })).toBeEnabled();
  });
});
