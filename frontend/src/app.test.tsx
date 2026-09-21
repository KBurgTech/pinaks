import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import { i18n } from "@/i18n";

import { App } from "./app";

vi.mock("@/api/client", () => ({ apiClient: { GET: vi.fn(), PUT: vi.fn() } }));

const get = vi.mocked(apiClient.GET);
const put = vi.mocked(apiClient.PUT);

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  window.history.pushState({}, "", "/app/");
  localStorage.clear();
  vi.clearAllMocks();
});

function capabilities(
  role: "admin" | "company_member" | "read_only",
  overrides: Partial<Record<string, boolean>> = {},
  features: Partial<Record<"payment_requests" | "reminders" | "time_tracking", boolean>> = {},
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
      features: {
        payment_requests: false,
        reminders: false,
        time_tracking: false,
        ...features,
      },
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

  it("shows enabled installation features from backend capabilities", async () => {
    capabilities("company_member", {}, { payment_requests: true });
    render(<App />);

    const navigation = await screen.findByRole("navigation", { name: "Main navigation" });
    expect(navigation).toHaveTextContent("Payment requests");
    expect(navigation).not.toHaveTextContent("Reminders");
  });

  it("loads and saves the bilingual company settings form for administrators", async () => {
    window.history.pushState({}, "", "/app/settings/");
    const profile = {
      legal_name: "Beispiel GmbH",
      address_line_1: "Musterstraße 1",
      address_line_2: "",
      postal_code: "10115",
      city: "Berlin",
      country_code: "DE",
      email: "rechnung@example.test",
      phone: "",
      tax_number: "12/345/67890",
      vat_identifier: "DE123456789",
      company_identifier: "HRB 12345",
      bank_account_holder: "Beispiel GmbH",
      iban: "DE89370400440532013000",
      bic: "COBADEFFXXX",
      payment_instructions: "Bitte innerhalb von 14 Tagen zahlen.",
      default_currency: "EUR" as const,
      default_locale: "de-DE" as const,
      default_ui_language: "de" as const,
      default_document_language: "de" as const,
      invoice_number_prefix: "RE-",
      invoice_number_next: 1000,
      invoice_number_padding: 6,
      invoice_number_reset: "annual" as const,
      features: {
        payment_requests: true,
        reminders: false,
        time_tracking: false,
      },
    };
    get.mockImplementation(async (path) => {
      if (path === "/api/v1/capabilities/") {
        return {
          data: {
            role: "admin",
            capabilities: {
              read: true,
              draft_mutation: true,
              invoice_issuance: true,
              payment_management: true,
              administration: true,
            },
            features: profile.features,
          },
          response: new Response(null, { status: 200 }),
        };
      }
      return {
        data: profile,
        response: new Response(null, { status: 200 }),
      };
    });
    put.mockResolvedValue({
      data: { ...profile, legal_name: "Neue GmbH" },
      response: new Response(null, { status: 200 }),
    });

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Company settings" })).toBeInTheDocument();
    const legalName = screen.getByRole("textbox", { name: "Legal name" });
    fireEvent.change(legalName, { target: { value: "Neue GmbH" } });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    await waitFor(() => {
      expect(put).toHaveBeenCalledWith("/api/v1/configuration/company/", {
        body: expect.objectContaining({ legal_name: "Neue GmbH" }),
      });
    });
    expect(await screen.findByText("Settings saved.")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Deutsch" }));
    expect(
      await screen.findByRole("heading", { name: "Unternehmenseinstellungen" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Rechtlicher Name" })).toBeInTheDocument();
  });

  it("maps backend field errors onto the company form", async () => {
    window.history.pushState({}, "", "/app/settings/");
    capabilities("admin");
    get.mockResolvedValueOnce({
      data: {
        role: "admin",
        capabilities: {
          read: true,
          draft_mutation: true,
          invoice_issuance: true,
          payment_management: true,
          administration: true,
        },
        features: { payment_requests: false, reminders: false, time_tracking: false },
      },
      response: new Response(null, { status: 200 }),
    });
    get.mockResolvedValueOnce({
      error: {
        error: {
          code: "not_found",
          message: "Company configuration has not been created.",
          fields: {},
        },
      },
      response: new Response(null, { status: 404 }),
    });
    put.mockResolvedValue({
      error: {
        error: {
          code: "validation_error",
          message: "Request validation failed.",
          fields: {
            legal_name: [{ code: "blank", message: "This field may not be blank." }],
          },
        },
      },
      response: new Response(null, { status: 400 }),
    });

    render(<App />);

    const legalName = await screen.findByRole("textbox", { name: "Legal name" });
    fireEvent.change(legalName, { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save settings" }));

    expect(await screen.findByText("Enter a legal name.")).toBeInTheDocument();
    expect(legalName).toHaveAttribute("aria-invalid", "true");
  });
});
