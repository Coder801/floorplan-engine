import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GoogleButton } from "./index";

describe("GoogleButton", () => {
  it("is a link with the caller's label", () => {
    render(<GoogleButton href="/api/auth/google" label="Продолжить с Google" />);
    expect(screen.getByRole("link", { name: "Продолжить с Google" })).toHaveAttribute("href", "/api/auth/google");
  });
});
