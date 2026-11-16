import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { stubApi, text } from "@/shared/testApi";
import { summary } from "@/shared/testData";
import { ProjectCard } from "./index";

describe("ProjectCard", () => {
  it("shows the title, folder, stages, build and questions; a click opens the project by its key", async () => {
    const onOpen = vi.fn();
    render(<ProjectCard p={summary({ open_questions: 3, stale: true, stages: [
      { stage: "plan", status: "ready" }, { stage: "plumbing", status: "absent" },
    ] })} onOpen={onOpen} />);
    const card = screen.getByRole("button", { name: /Квартира 42/ });
    expect(card).toHaveTextContent("kv42");
    expect(card).toHaveTextContent("План");
    expect(card).not.toHaveTextContent("Сантехника");
    expect(screen.getByText("План")).toHaveAttribute("title", "строится");
    expect(card).toHaveTextContent(/собран \d+ ноября 2025/);
    expect(card).toHaveTextContent("вопросов: 3");
    expect(card).toHaveTextContent("устарел");
    expect(card).not.toHaveAttribute("aria-current");
    await userEvent.click(card);
    expect(onOpen).toHaveBeenCalledWith("p1");
  });

  it("an unbuilt project says so; the current one is marked", () => {
    render(<ProjectCard p={summary({ built: null })} onOpen={vi.fn()} current />);
    const card = screen.getByRole("button");
    expect(card).toHaveTextContent("не собран");
    expect(card).toHaveAttribute("aria-current", "true");
  });

  it("loads the plan preview of the build", async () => {
    const sent = stubApi({ "GET /api/projects/p1/out/preview.svg": text('<svg data-testid="preview"></svg>') });
    render(<ProjectCard p={summary({ preview: true })} onOpen={vi.fn()} />);
    expect(await screen.findByTestId("preview")).toBeInTheDocument();
    expect(sent[0].path).toBe("/api/projects/p1/out/preview.svg?t=1763200000");
  });
});
