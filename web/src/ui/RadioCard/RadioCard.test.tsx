import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { RadioCard } from "./index";

describe("RadioCard", () => {
  it("a click on the card picks its value", async () => {
    const onChange = vi.fn();
    render(
      <fieldset>
        <RadioCard name="kind" value="studio" checked onChange={onChange} title="Студия" description="Проекты для заказчиков" />
        <RadioCard name="kind" value="personal" checked={false} onChange={onChange} title="Мой ремонт" />
      </fieldset>,
    );
    expect(screen.getByRole("radio", { name: /Студия/ })).toBeChecked();
    expect(screen.getByText("Проекты для заказчиков")).toBeInTheDocument();
    await userEvent.click(screen.getByText("Мой ремонт"));
    expect(onChange).toHaveBeenCalledWith("personal");
  });

  it("a disabled card cannot be picked", async () => {
    const onChange = vi.fn();
    render(<RadioCard name="kind" value="studio" checked={false} onChange={onChange} title="Студия" disabled />);
    expect(screen.getByRole("radio")).toBeDisabled();
    await userEvent.click(screen.getByText("Студия"));
    expect(onChange).not.toHaveBeenCalled();
  });
});
