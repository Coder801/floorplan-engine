import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CLIENT, draftState, workState } from "@/widgets/WorkStage/mock";
import { WorkSummary } from "./index";

describe("WorkSummary", () => {
  it("sums the plan: state, approval, accepted, money, lines without a price", () => {
    render(<WorkSummary state={workState()} />);
    expect(screen.getByText("Утверждён", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText(/Ирина \(студия\)/)).toBeInTheDocument();
    expect(screen.getByText("Утверждён студией за заказчика — по звонку: звонок 2.11, Андрей")).toBeInTheDocument();
    expect(screen.getByText("1 из 7")).toBeInTheDocument();
    expect(screen.getByText("Осталось оплатить")).toBeInTheDocument();
    expect(screen.getByText(/Строк без цены: 1/)).toBeInTheDocument();
  });

  it("nothing to show without a plan, or a draft to the client", () => {
    const { rerender } = render(<WorkSummary state={null} />);
    expect(screen.getByText("Плана работ пока нет.")).toBeInTheDocument();
    rerender(<WorkSummary state={draftState("draft", CLIENT)} />);
    expect(screen.getByText("Плана работ пока нет.")).toBeInTheDocument();
  });
});
