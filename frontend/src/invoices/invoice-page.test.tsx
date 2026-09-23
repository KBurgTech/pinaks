import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import { i18n } from "@/i18n";
import { InvoicePage } from "./invoice-page";

vi.mock("@/api/client", () => ({ apiClient: { GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() } }));
const get = vi.mocked(apiClient.GET);
const post = vi.mocked(apiClient.POST);
const patch = vi.mocked(apiClient.PATCH);
const response = <T,>(data: T, status = 200) => ({
  data,
  response: new Response(null, { status }),
});
const customer = {
  id: 3,
  customer_number: "C-3",
  display_name: "Ada Lovelace",
  is_archived: false,
};
const invoice = {
  id: 7,
  customer_id: 3,
  invoice_type: "STANDARD",
  lifecycle_status: "DRAFT",
  payment_status: "UNPAID",
  is_overdue: false,
  invoice_number: null,
  currency: "EUR",
  document_language: "en",
  issue_date: "2026-09-23",
  due_date: null,
  recipient: {},
  lines: [],
  subtotal: "0.00",
  tax_total: "0.00",
  grand_total: "0.00",
  version: 1,
  created_at: "2026-09-23T00:00:00Z",
  modified_at: "2026-09-23T00:00:00Z",
};

function mount(canMutate = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 30_000 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <InvoicePage canMutate={canMutate} />
    </QueryClientProvider>,
  );
}

beforeEach(async () => {
  await i18n.changeLanguage("en");
  window.history.pushState({}, "", "/app/invoices/");
  get.mockImplementation((path) => {
    if (path === "/api/v1/invoices/")
      return Promise.resolve(response({ count: 0, results: [], next: null, previous: null }));
    if (path === "/api/v1/customers/")
      return Promise.resolve(
        response({ count: 1, results: [customer], next: null, previous: null }),
      );
    if (path === "/api/v1/catalog/")
      return Promise.resolve(response({ count: 0, results: [], next: null, previous: null }));
    if (path === "/api/v1/invoices/{invoice_id}/") return Promise.resolve(response(invoice));
    return Promise.resolve(response([]));
  });
});
afterEach(() => {
  vi.clearAllMocks();
});

describe("draft invoice page", () => {
  it("creates a draft and displays only saved backend totals", async () => {
    post.mockResolvedValue(response(invoice, 201));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "New invoice" }));
    fireEvent.change(screen.getByLabelText("Customer"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Create draft" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/invoices/", { body: { customer_id: 3 } }),
    );
    expect(await screen.findAllByText("0.00 EUR")).toHaveLength(3);
  });

  it("refreshes the list when returning from a newly created invoice", async () => {
    let listCalls = 0;
    get.mockImplementation((path) => {
      if (path === "/api/v1/invoices/") {
        listCalls += 1;
        return Promise.resolve(
          response({
            count: listCalls === 1 ? 0 : 1,
            results: listCalls === 1 ? [] : [invoice],
            next: null,
            previous: null,
          }),
        );
      }
      if (path === "/api/v1/customers/")
        return Promise.resolve(
          response({ count: 1, results: [customer], next: null, previous: null }),
        );
      return Promise.resolve(response(invoice));
    });
    post.mockResolvedValue(response(invoice, 201));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "New invoice" }));
    fireEvent.change(await screen.findByLabelText("Customer"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Create draft" }));
    await screen.findByRole("heading", { name: "Invoice draft" });
    fireEvent.click(screen.getByRole("button", { name: "Back to invoices" }));
    expect(await screen.findByRole("button", { name: "Open invoice" })).toBeInTheDocument();
    expect(listCalls).toBe(2);
  });

  it("shows a recoverable error when creation cannot reach the API", async () => {
    post.mockRejectedValue(new Error("offline"));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "New invoice" }));
    fireEvent.change(await screen.findByLabelText("Customer"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Create draft" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The draft could not be saved.");
    expect(screen.getByRole("button", { name: "Create draft" })).toBeEnabled();
  });

  it("saves a manual line with the current version and shows the returned total", async () => {
    window.history.pushState({}, "", "/app/invoices/7/");
    patch.mockResolvedValue(
      response({
        ...invoice,
        version: 2,
        grand_total: "119.00",
        subtotal: "100.00",
        tax_total: "19.00",
      }),
    );
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Add manual line" }));
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "Consulting" } });
    fireEvent.change(screen.getByLabelText("Unit price"), { target: { value: "100.00" } });
    fireEvent.click(screen.getByRole("button", { name: "Save line" }));
    await waitFor(() => expect(patch).toHaveBeenCalledOnce());
    expect(patch.mock.calls[0]?.[0]).toBe("/api/v1/invoices/{invoice_id}/");
    expect(patch.mock.calls[0]?.[1]).toMatchObject({
      body: {
        expected_version: 1,
        line_operations: [{ action: "add", description: "Consulting", unit_price: "100.00" }],
      },
    });
    expect(await screen.findByText("119.00 EUR")).toBeInTheDocument();
  });

  it("offers reload after a stale version without overwriting", async () => {
    window.history.pushState({}, "", "/app/invoices/7/");
    patch.mockResolvedValue({
      error: { error: { code: "stale_invoice_version", message: "stale", fields: {} } },
      response: new Response(null, { status: 409 }),
    });
    mount();
    fireEvent.change(await screen.findByLabelText("Due date"), { target: { value: "2026-10-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findByRole("button", { name: "Reload invoice" })).toBeInTheDocument();
    expect(patch).toHaveBeenCalledOnce();
  });

  it("shows read-only details without mutation controls", async () => {
    window.history.pushState({}, "", "/app/invoices/7/");
    mount(false);
    expect(await screen.findAllByText("0.00 EUR")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: "Save draft" })).not.toBeInTheDocument();
  });

  it("copies a catalog selection without sending catalog pricing", async () => {
    window.history.pushState({}, "", "/app/invoices/7/");
    get.mockImplementation((path) => {
      if (path === "/api/v1/invoices/{invoice_id}/") return Promise.resolve(response(invoice));
      if (path === "/api/v1/catalog/")
        return Promise.resolve(
          response({
            count: 1,
            results: [{ id: 5, code: "CONSULT", description_en: "Consulting", is_archived: false }],
            next: null,
            previous: null,
          }),
        );
      return Promise.resolve(response({ count: 0, results: [], next: null, previous: null }));
    });
    patch.mockResolvedValue(response({ ...invoice, version: 2 }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Add catalog item" }));
    await screen.findByRole("option", { name: "CONSULT — Consulting" });
    fireEvent.change(screen.getByLabelText("Catalog item"), { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save line" }));
    await waitFor(() => expect(patch).toHaveBeenCalledOnce());
    expect(patch.mock.calls[0]?.[1]).toMatchObject({
      body: {
        line_operations: [
          { action: "add", catalog_item_id: 5, quantity: "1", discount_percent: "0" },
        ],
      },
    });
  });

  it.each([
    ["customer", { source: "customer" }],
    ["known_customer", { source: "known_customer", customer_id: 3 }],
    ["saved", { source: "saved", recipient_id: 9 }],
    [
      "manual",
      {
        source: "manual",
        values: { given_name: "Ada", address_line_1: "Main 1" },
      },
    ],
  ])("saves the %s recipient variant", async (source, recipient) => {
    window.history.pushState({}, "", "/app/invoices/7/");
    get.mockImplementation((path) => {
      if (path === "/api/v1/invoices/{invoice_id}/") return Promise.resolve(response(invoice));
      if (path === "/api/v1/customers/")
        return Promise.resolve(
          response({ count: 1, results: [customer], next: null, previous: null }),
        );
      if (path === "/api/v1/customers/{customer_id}/billing-recipients/")
        return Promise.resolve(response([{ id: 9, display_name: "Saved Ada" }]));
      return Promise.resolve(response([]));
    });
    patch.mockResolvedValue(response({ ...invoice, version: 2 }));
    mount();
    fireEvent.change(await screen.findByLabelText("Billing recipient"), {
      target: { value: source },
    });
    if (source === "known_customer")
      fireEvent.change(await screen.findByLabelText("Recipient customer"), {
        target: { value: "3" },
      });
    if (source === "saved") {
      await screen.findByRole("option", { name: "Saved Ada" });
      fireEvent.change(screen.getByLabelText("Saved recipient record"), { target: { value: "9" } });
    }
    if (source === "manual") {
      fireEvent.change(screen.getByLabelText("Given name"), { target: { value: "Ada" } });
      fireEvent.change(screen.getByLabelText("Family name"), { target: { value: "Lovelace" } });
      fireEvent.change(screen.getByLabelText("Address line 1"), { target: { value: "Main 1" } });
      fireEvent.change(screen.getByLabelText("Postal code"), { target: { value: "10115" } });
      fireEvent.change(screen.getByLabelText("City"), { target: { value: "Berlin" } });
    }
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    await waitFor(() => expect(patch).toHaveBeenCalledOnce());
    expect(patch.mock.calls[0]?.[1]).toMatchObject({ body: { recipient } });
  });

  it("sends line reorder and remove commands with the latest version", async () => {
    window.history.pushState({}, "", "/app/invoices/7/");
    const line = (id: number, description: string, position: number) => ({
      id,
      description,
      position,
      quantity: "1",
      unit_price: "10.00",
      gross_total: "10.00",
      net_total: "10.00",
      tax_total: "0.00",
      service_date: null,
      service_period_end: null,
      item_code: "",
      unit: "C62",
      discount_percent: "0.00",
      tax_category: "E",
      tax_rate: "0.00",
      price_entry_policy: "net",
      exemption_reason_code: "",
      exemption_wording: "",
    });
    const first = line(11, "First", 1);
    const second = line(12, "Second", 2);
    get.mockImplementation((path) =>
      path === "/api/v1/invoices/{invoice_id}/"
        ? Promise.resolve(response({ ...invoice, lines: [first, second] }))
        : Promise.resolve(response({ count: 0, results: [], next: null, previous: null })),
    );
    patch
      .mockResolvedValueOnce(response({ ...invoice, version: 2, lines: [second, first] }))
      .mockResolvedValueOnce(response({ ...invoice, version: 3, lines: [second] }));
    mount();
    fireEvent.click(await screen.findByRole("button", { name: "Move down First" }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith(
        "/api/v1/invoices/{invoice_id}/",
        expect.objectContaining({
          body: {
            expected_version: 1,
            line_operations: [{ action: "update", line_id: 11, position: 2 }],
          },
        }),
      ),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Remove First" }));
    await waitFor(() =>
      expect(patch).toHaveBeenLastCalledWith(
        "/api/v1/invoices/{invoice_id}/",
        expect.objectContaining({
          body: { expected_version: 2, line_operations: [{ action: "remove", line_id: 11 }] },
        }),
      ),
    );
  });

  it("shows field validation and keeps unsaved changes for review", async () => {
    window.history.pushState({}, "", "/app/invoices/7/");
    patch.mockResolvedValue({
      error: {
        error: {
          code: "validation_error",
          message: "invalid",
          fields: { due_date: [{ code: "invalid", message: "Date is too early" }] },
        },
      },
      response: new Response(null, { status: 400 }),
    });
    mount();
    fireEvent.change(await screen.findByLabelText("Due date"), { target: { value: "2026-01-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Save draft" }));
    expect(await screen.findAllByText("Date is too early")).toHaveLength(2);
    expect(screen.getByLabelText("Due date")).toHaveValue("2026-01-01");
    expect(screen.getByRole("status")).toHaveTextContent("You have unsaved changes.");
  });

  it("shows the saved recipient snapshot in read-only mode", async () => {
    window.history.pushState({}, "", "/app/invoices/7/");
    get.mockImplementation((path) =>
      path === "/api/v1/invoices/{invoice_id}/"
        ? Promise.resolve(
            response({
              ...invoice,
              recipient: {
                party_type: "person",
                given_name: "Grace",
                family_name: "Hopper",
                address_line_1: "Main 1",
                postal_code: "10115",
                city: "Berlin",
                country_code: "DE",
              },
            }),
          )
        : Promise.resolve(response({ count: 0, results: [], next: null, previous: null })),
    );
    mount(false);
    expect(await screen.findByDisplayValue("Grace")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Grace")).toBeDisabled();
  });

  it("keeps unsaved draft fields when line controls are used", async () => {
    window.history.pushState({}, "", "/app/invoices/7/");
    mount();
    fireEvent.change(await screen.findByLabelText("Due date"), { target: { value: "2026-10-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Add manual line" }));
    expect(screen.getByLabelText("Due date")).toHaveValue("2026-10-01");
    expect(screen.getByRole("button", { name: "Save line" })).toBeDisabled();
  });

  it("shows empty and error states and bilingual labels", async () => {
    const view = mount(false);
    expect(await screen.findByText("No invoices yet.")).toBeInTheDocument();
    view.unmount();
    await i18n.changeLanguage("de");
    get.mockRejectedValue(new Error("offline"));
    mount(false);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Rechnungen konnten nicht geladen werden.",
    );
  });
  it("saves and applies a preset in both languages", async () => {
    window.history.pushState({}, "", "/app/invoices/7/");
    const existing = {
      ...invoice,
      lines: [
        {
          id: 11,
          position: 1,
          description: "Consulting",
          item_code: "WORK",
          unit: "HUR",
          quantity: "2.0000",
          unit_price: "10.00",
          discount_percent: "0.00",
          tax_category: "S",
          tax_rate: "19.00",
          price_entry_policy: "net",
          exemption_reason_code: "",
          exemption_wording: "",
          service_date: null,
          service_period_end: null,
          net_total: "20.00",
          tax_total: "3.80",
          gross_total: "23.80",
        },
      ],
    };
    const preset = { id: 5, name: "Routine", lines: existing.lines, is_archived: false };
    get.mockImplementation((path) =>
      Promise.resolve(
        response(
          path === "/api/v1/invoices/{invoice_id}/"
            ? existing
            : path === "/api/v1/invoice-presets/"
              ? [preset]
              : [],
        ),
      ),
    );
    post.mockImplementation((path) =>
      Promise.resolve(
        response(
          path === "/api/v1/invoice-presets/" ? preset : { ...existing, version: 2 },
          path === "/api/v1/invoice-presets/" ? 201 : 200,
        ),
      ),
    );
    mount();
    expect(await screen.findByRole("option", { name: "Routine" })).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Preset"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Apply mode"), { target: { value: "replace" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply preset" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/invoices/{invoice_id}/apply-preset/", {
        params: { path: { invoice_id: 7 } },
        body: { preset_id: 5, expected_version: 1, mode: "replace" },
      }),
    );
    await i18n.changeLanguage("de");
    expect(screen.getByLabelText("Vorlage")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Vorlage anwenden" })).toBeInTheDocument();
  });
});
