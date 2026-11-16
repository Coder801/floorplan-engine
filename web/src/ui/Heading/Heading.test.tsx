import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Heading } from "./index";

describe("Heading", () => {
  it("is a heading of its level, whatever the size", () => {
    render(<><Heading level={1}>Проекты</Heading><Heading level={3} size="caps" id="groups">Группы</Heading></>);
    expect(screen.getByRole("heading", { level: 1, name: "Проекты" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 3, name: "Группы" })).toHaveAttribute("id", "groups");
  });
});
