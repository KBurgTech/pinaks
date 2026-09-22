import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import { i18n } from "@/i18n";

import { CatalogPage } from "./catalog-page";

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

const taxProfile = {
  id: 3,
  code: "standard-19",
  version: 1,
  name: "Standard 19%",
  tax_category: "S" as const,
  rate: "19.00",
  exemption_reason_code: "",
  exemption_wording_en: "",
  exemption_wording_de: "",
  price_entry_policy: "net" as const,
  tax_column_policy: "show" as const,
  required_seller_identifiers: ["tax_number"] as const,
  is_default: true,
  is_current: true,
  translation_complete: true,
};

const item = {
  id: 7,
  code: "CONSULTING",
  description_en: "Consulting hour",
  description_de: "Beratungsstunde",
  unit: "HUR" as const,
  default_price: "1234567890.12",
  minimum_price: "100.10",
  maximum_price: "1500000000.99",
  default_tax_profile: {
    id: 3,
    code: "standard-19",
    version: 1,
    name: "Standard 19%",
    rate: "19.00",
    tax_category: "S",
  },
  is_archived: false,
};

function page(data = [item], canMutate = true, listError = false, hasNextPage = false) {
  get.mockImplementation((path) => {
    if (path === "/api/v1/catalog/") {
      if (listError) {
        return Promise.resolve({
          error: { error: { code: "server_error", message: "No", fields: {} } },
          response: new Response(null, { status: 500 }),
        });
      }
      return Promise.resolve({
        data: {
          count: hasNextPage ? 26 : data.length,
          next: hasNextPage ? "http://test/api/v1/catalog/?page=2" : null,
          previous: null,
          results: data,
        },
        response: new Response(null, { status: 200 }),
      });
    }
    if (path === "/api/v1/configuration/tax-profiles/") {
      return Promise.resolve({ data: [taxProfile], response: new Response(null, { status: 200 }) });
    }
    return Promise.resolve({ data: item, response: new Response(null, { status: 200 }) });
  });
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <CatalogPage canMutate={canMutate} />
    </QueryClientProvider>,
  );
}

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("catalog management", () => {
  it("renders loading, empty, and error list states", async () => {
    let resolveList: ((value: object) => void) | undefined;
    get.mockReturnValueOnce(new Promise((resolve) => (resolveList = resolve)));
    const view = page();
    expect(screen.getByText("Loading catalog…")).toBeInTheDocument();
    resolveList?.({
      data: { count: 0, next: null, previous: null, results: [] },
      response: new Response(null, { status: 200 }),
    });
    expect(await screen.findByText("No catalog items match this view.")).toBeInTheDocument();

    view.unmount();
    get.mockReset();
    page([], true, true);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Catalog items could not be loaded.",
    );
  });

  it("searches, pages, and displays locale-aware prices and both descriptions", async () => {
    page([item], true, false, true);

    expect(await screen.findByRole("cell", { name: "Consulting hour" })).toBeInTheDocument();
    expect(screen.getByRole("cell", { name: "Beratungsstunde" })).toBeInTheDocument();
    expect(screen.getByText("€1,234,567,890.12")).toBeInTheDocument();
    expect(screen.getByText("Translations complete")).toBeInTheDocument();
    fireEvent.change(screen.getByRole("searchbox", { name: "Search catalog" }), {
      target: { value: "consult" },
    });
    fireEvent.submit(screen.getByRole("search"));
    fireEvent.click(await screen.findByRole("button", { name: "Next page" }));

    await waitFor(() =>
      expect(get).toHaveBeenCalledWith("/api/v1/catalog/", {
        params: {
          query: { archived: false, page: 2, page_size: 25, search: "consult" },
        },
      }),
    );
  });

  it("creates and edits while round-tripping decimal strings unchanged", async () => {
    page([]);
    post.mockResolvedValueOnce({ data: item, response: new Response(null, { status: 201 }) });

    fireEvent.click(await screen.findByRole("button", { name: "New catalog item" }));
    expect(screen.getByLabelText("Item code")).toHaveFocus();
    fireEvent.change(screen.getByLabelText("Item code"), { target: { value: "CONSULTING" } });
    fireEvent.change(screen.getByLabelText("English description"), {
      target: { value: "Consulting hour" },
    });
    fireEvent.change(screen.getByLabelText("German description"), {
      target: { value: "Beratungsstunde" },
    });
    fireEvent.change(screen.getByLabelText("Unit"), { target: { value: "HUR" } });
    fireEvent.change(screen.getByLabelText("Default price"), {
      target: { value: "1234567890.12" },
    });
    fireEvent.change(screen.getByLabelText("Default tax profile"), { target: { value: "3" } });
    fireEvent.click(screen.getByRole("button", { name: "Create catalog item" }));

    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/catalog/", {
        body: {
          code: "CONSULTING",
          description_en: "Consulting hour",
          description_de: "Beratungsstunde",
          unit: "HUR",
          default_price: "1234567890.12",
          minimum_price: null,
          maximum_price: null,
          default_tax_profile_id: 3,
        },
      }),
    );

    fireEvent.click(await screen.findByRole("button", { name: "Edit catalog item" }));
    expect(screen.getByLabelText("Item code")).toBeDisabled();
    patch.mockResolvedValueOnce({
      data: { ...item, default_price: "1234567890.13" },
      response: new Response(null, { status: 200 }),
    });
    fireEvent.change(screen.getByLabelText("Default price"), {
      target: { value: "1234567890.13" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save catalog item" }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/api/v1/catalog/{item_id}/", {
        params: { path: { item_id: 7 } },
        body: {
          code: "CONSULTING",
          description_en: "Consulting hour",
          description_de: "Beratungsstunde",
          unit: "HUR",
          default_price: "1234567890.13",
          minimum_price: "100.10",
          maximum_price: "1500000000.99",
          default_tax_profile_id: 3,
        },
      }),
    );
  });

  it("maps backend validation errors and archives after accessible confirmation", async () => {
    page([]);
    post.mockResolvedValueOnce({
      error: {
        error: {
          code: "validation_error",
          message: "Request validation failed.",
          fields: { description_de: [{ code: "required", message: "Required in German." }] },
        },
      },
      response: new Response(null, { status: 400 }),
    });
    fireEvent.click(await screen.findByRole("button", { name: "New catalog item" }));
    fireEvent.click(screen.getByRole("button", { name: "Create catalog item" }));
    expect(await screen.findByText("Required in German.")).toBeInTheDocument();
    expect(screen.getByLabelText("German description")).toHaveAttribute("aria-invalid", "true");

    post.mockResolvedValueOnce({ data: item, response: new Response(null, { status: 201 }) });
    fireEvent.click(screen.getByRole("button", { name: "Create catalog item" }));
    await screen.findByRole("heading", { name: "CONSULTING" });
    deleteRequest.mockResolvedValueOnce({
      data: undefined,
      response: new Response(null, { status: 204 }),
    });
    fireEvent.click(screen.getByRole("button", { name: "Archive catalog item" }));
    const dialog = await screen.findByRole("dialog", { name: "Archive CONSULTING?" });
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus(),
    );
    fireEvent.click(within(dialog).getByRole("button", { name: "Archive" }));
    await waitFor(() =>
      expect(deleteRequest).toHaveBeenCalledWith("/api/v1/catalog/{item_id}/", {
        params: { path: { item_id: 7 } },
      }),
    );
  });

  it("renders read-only access and the complete German workflow", async () => {
    page([item], false);
    expect(await screen.findByText("Read-only access")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New catalog item" })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "View CONSULTING" }));
    expect(
      screen.getByText("You can view catalog items, but you cannot change them."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit catalog item" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive catalog item" })).not.toBeInTheDocument();

    await i18n.changeLanguage("de");
    expect(await screen.findByRole("button", { name: "Zurück zum Katalog" })).toBeInTheDocument();
    expect(screen.getAllByText("Beratungsstunde")).toHaveLength(2);
  });
});
