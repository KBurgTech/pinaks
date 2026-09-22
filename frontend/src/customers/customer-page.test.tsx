import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import { i18n } from "@/i18n";

import { CustomerPage } from "./customer-page";

vi.mock("@/api/client", () => ({
  apiClient: {
    DELETE: vi.fn(),
    GET: vi.fn(),
    PATCH: vi.fn(),
    POST: vi.fn(),
  },
}));

const deleteRequest = vi.mocked(apiClient.DELETE);
const get = vi.mocked(apiClient.GET);
const patch = vi.mocked(apiClient.PATCH);
const post = vi.mocked(apiClient.POST);

const customer = {
  id: 7,
  customer_number: "C-0007",
  party_type: "person" as const,
  given_name: "Ada",
  family_name: "Lovelace",
  organization_name: "",
  display_name: "Ada Lovelace",
  email: "ada@example.test",
  phone: "+49 30 123456",
  preferred_language: "en" as const,
  is_archived: false,
  addresses: [
    {
      id: 3,
      label: "home",
      address_line_1: "Musterstrasse 1",
      address_line_2: "",
      postal_code: "10115",
      city: "Berlin",
      country_code: "DE",
      is_primary: true,
    },
  ],
};

function page(data = [customer], canMutate = true, listError = false) {
  get.mockImplementation((path) => {
    if (path === "/api/v1/customers/") {
      if (listError) {
        return Promise.resolve({
          error: { error: { code: "server_error", message: "No", fields: {} } },
          response: new Response(null, { status: 500 }),
        });
      }
      return Promise.resolve({
        data: { count: data.length, next: null, previous: null, results: data },
        response: new Response(null, { status: 200 }),
      });
    }
    if (path === "/api/v1/customers/{customer_id}/billing-recipients/") {
      return Promise.resolve({ data: [], response: new Response(null, { status: 200 }) });
    }
    return Promise.resolve({ data: customer, response: new Response(null, { status: 200 }) });
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CustomerPage canMutate={canMutate} />
    </QueryClientProvider>,
  );
}

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("customer management", () => {
  it("renders loading, empty, and error list states", async () => {
    let resolveList: ((value: object) => void) | undefined;
    get.mockReturnValueOnce(new Promise((resolve) => (resolveList = resolve)));
    const view = page();
    expect(screen.getByText("Loading customers…")).toBeInTheDocument();
    resolveList?.({
      data: { count: 0, next: null, previous: null, results: [] },
      response: new Response(null, { status: 200 }),
    });
    expect(await screen.findByText("No customers match this view.")).toBeInTheDocument();

    view.unmount();
    get.mockReset();
    page([], true, true);
    expect(await screen.findByRole("alert")).toHaveTextContent("Customers could not be loaded.");
  });

  it("searches the customer list and opens an information-dense detail", async () => {
    page();
    expect(await screen.findByRole("cell", { name: "Ada Lovelace" })).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search customers" }), {
      target: { value: "Ada" },
    });
    fireEvent.submit(screen.getByRole("search"));

    await waitFor(() =>
      expect(get).toHaveBeenCalledWith("/api/v1/customers/", {
        params: { query: { archived: false, page: 1, page_size: 25, search: "Ada" } },
      }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "View Ada Lovelace" }));
    expect(await screen.findByRole("heading", { name: "Ada Lovelace" })).toBeInTheDocument();
    expect(
      screen.getByText(
        (_, element) =>
          element?.tagName === "DD" && element.textContent?.includes("Musterstrasse 1") === true,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("English")).toBeInTheDocument();
  });

  it("creates a customer and maps authoritative backend field errors", async () => {
    page([]);
    post.mockResolvedValueOnce({
      error: {
        error: {
          code: "validation_error",
          message: "Request validation failed.",
          fields: { customer_number: [{ code: "unique", message: "Already exists." }] },
        },
      },
      response: new Response(null, { status: 400 }),
    });

    await screen.findByText("No customers match this view.");
    fireEvent.click(screen.getByRole("button", { name: "New customer" }));
    fireEvent.change(screen.getByLabelText("Customer number"), { target: { value: "C-0007" } });
    fireEvent.change(screen.getByLabelText("Given name"), { target: { value: "Ada" } });
    fireEvent.change(screen.getByLabelText("Family name"), { target: { value: "Lovelace" } });
    fireEvent.click(screen.getByRole("button", { name: "Create customer" }));

    expect(await screen.findByText("Already exists.")).toBeInTheDocument();
    expect(screen.getByLabelText("Customer number")).toHaveAttribute("aria-invalid", "true");
    expect(post).toHaveBeenCalledWith("/api/v1/customers/", {
      body: {
        customer_number: "C-0007",
        party_type: "person",
        given_name: "Ada",
        family_name: "Lovelace",
        organization_name: "",
        email: "",
        phone: "",
        preferred_language: "en",
        addresses: [
          {
            label: "primary",
            address_line_1: "",
            address_line_2: "",
            postal_code: "",
            city: "",
            country_code: "DE",
            is_primary: true,
          },
        ],
      },
    });

    post.mockResolvedValueOnce({
      data: customer,
      response: new Response(null, { status: 201 }),
    });
    fireEvent.click(screen.getByRole("button", { name: "Create customer" }));
    expect(await screen.findByRole("heading", { name: "Ada Lovelace" })).toBeInTheDocument();
    expect(post).toHaveBeenCalledTimes(2);
  });

  it("edits, adds an alternate recipient, and archives after confirmation", async () => {
    page();
    patch.mockResolvedValueOnce({
      data: { ...customer, phone: "+49 30 999" },
      response: new Response(null, { status: 200 }),
    });
    post.mockResolvedValueOnce({
      data: {
        id: 9,
        customer_id: 7,
        party_type: "organization",
        given_name: "",
        family_name: "",
        organization_name: "Payer GmbH",
        display_name: "Payer GmbH",
        email: "",
        phone: "",
        address_line_1: "",
        address_line_2: "",
        postal_code: "",
        city: "",
        country_code: "DE",
      },
      response: new Response(null, { status: 201 }),
    });
    deleteRequest.mockResolvedValueOnce({
      data: undefined,
      response: new Response(null, { status: 204 }),
    });

    fireEvent.click(await screen.findByRole("button", { name: "View Ada Lovelace" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit customer" }));
    fireEvent.change(screen.getByLabelText("Phone"), { target: { value: "+49 30 999" } });
    fireEvent.click(screen.getByRole("button", { name: "Save customer" }));
    await waitFor(() => expect(patch).toHaveBeenCalledOnce());

    fireEvent.click(screen.getByRole("button", { name: "Add alternate recipient" }));
    fireEvent.change(screen.getByLabelText("Recipient type"), {
      target: { value: "organization" },
    });
    fireEvent.change(screen.getByLabelText("Recipient organization"), {
      target: { value: "Payer GmbH" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save recipient" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole("button", { name: "Archive customer" }));
    const dialog = await screen.findByRole("dialog", { name: "Archive Ada Lovelace?" });
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus(),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Archive" }));
    await waitFor(() =>
      expect(deleteRequest).toHaveBeenCalledWith("/api/v1/customers/{customer_id}/", {
        params: { path: { customer_id: 7 } },
      }),
    );
  });

  it("warns about unsaved edits and presents read-only access explicitly", async () => {
    const view = page();
    fireEvent.click(await screen.findByRole("button", { name: "View Ada Lovelace" }));
    fireEvent.click(screen.getByRole("button", { name: "Edit customer" }));
    fireEvent.change(screen.getByLabelText("Phone"), { target: { value: "changed" } });
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    const discardDialog = await screen.findByRole("dialog", {
      name: "Discard unsaved changes?",
    });
    expect(within(discardDialog).getByRole("button", { name: "Keep editing" })).toBeInTheDocument();
    fireEvent.click(within(discardDialog).getByRole("button", { name: "Discard changes" }));
    expect(await screen.findByRole("heading", { name: "Ada Lovelace" })).toBeInTheDocument();

    view.unmount();
    get.mockReset();
    page([customer], false);
    expect(await screen.findByText("Read-only access")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "View Ada Lovelace" }));
    expect(
      screen.getByText("You can view customer records, but you cannot change them."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit customer" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive customer" })).not.toBeInTheDocument();
  });

  it("keeps the complete workflow available in German", async () => {
    await i18n.changeLanguage("de");
    page([]);
    expect(await screen.findByRole("heading", { name: "Kunden" })).toBeInTheDocument();
    expect(screen.getByRole("searchbox", { name: "Kunden suchen" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Neuer Kunde" })).toBeInTheDocument();
    expect(await screen.findByText("Keine Kunden entsprechen dieser Ansicht.")).toBeInTheDocument();
  });
});
