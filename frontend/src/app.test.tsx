import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { App } from "./app";

describe("App scaffold", () => {
  it("identifies the application", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: "Pinaks" })).toBeInTheDocument();
  });
});
