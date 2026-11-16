import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AlphaNotice } from "./index";

describe("AlphaNotice", () => {
  it("shows once per browser: «Понятно» closes it for good", async () => {
    const user = userEvent.setup();
    const first = render(<AlphaNotice />);
    expect(await screen.findByRole("dialog", { name: /в альфа-тестировании/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Понятно, продолжить" })).toHaveFocus();
    expect(screen.queryByRole("button", { name: "Оставить отзыв" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Понятно, продолжить" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    first.unmount();
    render(<AlphaNotice />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("the feedback link closes it and opens the feedback form", async () => {
    const user = userEvent.setup();
    const onFeedback = vi.fn();
    render(<AlphaNotice onFeedback={onFeedback} />);
    await user.click(await screen.findByRole("button", { name: "Оставить отзыв" }));
    expect(onFeedback).toHaveBeenCalledOnce();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});
