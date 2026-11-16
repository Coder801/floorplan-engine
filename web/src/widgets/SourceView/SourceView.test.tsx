import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fail, stubApi, text } from "@/shared/testApi";
import { project } from "@/shared/testData";
import { SourceView } from "./index";

describe("SourceView", () => {
  it("shows a text source and goes back to the sheet", async () => {
    stubApi({ "GET /api/projects/p1/source/%D0%B7%D0%B0%D0%BC%D0%B5%D1%82%D0%BA%D0%B8.txt": text("Стена 4 м") });
    const onBack = vi.fn();
    render(<SourceView project={project()} file="заметки.txt" onBack={onBack} />);
    expect(await screen.findByText("Стена 4 м")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "← К листу" }));
    expect(onBack).toHaveBeenCalledOnce();
  });

  it("an image, a PDF, a file with no preview, a failed text", async () => {
    const { rerender } = render(<SourceView project={project()} file="dir/plan.png" onBack={vi.fn()} />);
    expect(screen.getByRole("img", { name: "dir/plan.png" })).toHaveAttribute("src", "/api/projects/p1/source/dir/plan.png");
    rerender(<SourceView project={project()} file="plan.pdf" onBack={vi.fn()} />);
    expect(screen.getByTitle("plan.pdf")).toHaveAttribute("src", "/api/projects/p1/source/plan.pdf");
    rerender(<SourceView project={project()} file="plan.dwg" onBack={vi.fn()} />);
    expect(screen.getByText("Предпросмотра нет — откройте файл в новой вкладке")).toBeInTheDocument();
    stubApi({ "GET /api/projects/p1/source/a.md": fail(404, "нет файла") });
    rerender(<SourceView project={project()} file="a.md" onBack={vi.fn()} />);
    expect(await screen.findByText("404: нет файла")).toBeInTheDocument();
  });
});
