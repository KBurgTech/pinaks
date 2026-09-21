import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";

import { App } from "./app";

vi.mock("@/api/client", () => ({ apiClient: { GET: vi.fn() } }));

const get = vi.mocked(apiClient.GET);

afterEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
});

function capabilities(
  role: "admin" | "company_member" | "read_only",
  overrides: Partial<Record<string, boolean>> = {},
) {
  get.mockResolvedValue({
    data: {
      role,
      capabilities: {
        read: true,
        draft_mutation: role !== "read_only",
        invoice_issuance: role !== "read_only",
        payment_management: role !== "read_only",
        administration: role === "admin",
        ...overrides,
      },
      features: {},
    },
    response: new Response(null, { status: 200 }),
  });
}

describe("application shell", () => {
  it("offers server-managed sign in when the session is missing", async () => {
    get.mockResolvedValue({
      error: {
        error: {
          code: "authentication_required",
          message: "Authentication credentials were not provided.",
          fields: {},
        },
      },
      response: new Response(null, { status: 403 }),
    });
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Sign in to Pinaks" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/accounts/login/?next=/app/",
    );
  });

  it("renders administration navigation only from the reported capability", async () => {
    capabilities("admin");
    render(<App />);

    const navigation = await screen.findByRole("navigation", { name: "Main navigation" });
    expect(navigation).toHaveTextContent("Customers");
    expect(navigation).toHaveTextContent("Invoices");
    expect(navigation).toHaveTextContent("Settings");
    expect(navigation).toHaveTextContent("Users");
    expect(screen.getByRole("link", { name: "New invoice" })).toBeInTheDocument();
  });

  it.each(["company_member", "read_only"] as const)(
    "does not render administration navigation for %s",
    async (role) => {
      capabilities(role);
      render(<App />);

      await screen.findByRole("navigation", { name: "Main navigation" });
      expect(screen.queryByText("Settings")).not.toBeInTheDocument();
      expect(screen.queryByText("Users")).not.toBeInTheDocument();
      if (role === "company_member") {
        expect(screen.getByRole("link", { name: "New invoice" })).toBeInTheDocument();
      } else {
        expect(screen.queryByRole("link", { name: "New invoice" })).not.toBeInTheDocument();
      }
    },
  );

  it("switches language, updates the document, and persists the preference", async () => {
    capabilities("read_only");
    render(<App />);
    await screen.findByRole("navigation", { name: "Main navigation" });
    fireEvent.click(screen.getByRole("button", { name: "Deutsch" }));

    await waitFor(() => {
      expect(screen.getByRole("navigation", { name: "Hauptnavigation" })).toHaveTextContent(
        "Kunden",
      );
    });
    expect(document.documentElement.lang).toBe("de");
    expect(localStorage.getItem("pinaks.uiLanguage")).toBe("de");
  });
});
