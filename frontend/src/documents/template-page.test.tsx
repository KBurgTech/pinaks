import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import { i18n } from "@/i18n";

import { TemplatePage } from "./template-page";

vi.mock("@/api/client", () => ({ apiClient: { GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() } }));

const get = vi.mocked(apiClient.GET);
const post = vi.mocked(apiClient.POST);

function renderPage() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <TemplatePage />
    </QueryClientProvider>,
  );
}

beforeEach(async () => {
  await i18n.changeLanguage("en");
  get.mockResolvedValue({ data: [], response: new Response(null, { status: 200 }) });
});

afterEach(() => vi.clearAllMocks());

it("creates a template and exposes labeled English and German source editors", async () => {
  post.mockResolvedValue({
    data: {
      id: 1,
      code: "invoice",
      name: "Invoice",
      created_at: "2026-09-23T00:00:00Z",
      versions: [],
    },
    response: new Response(null, { status: 201 }),
  });
  renderPage();
  expect(await screen.findByRole("heading", { name: "Document templates" })).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", { name: "Template code" }), {
    target: { value: "invoice" },
  });
  fireEvent.change(screen.getByRole("textbox", { name: "Template name" }), {
    target: { value: "Invoice" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create template" }));
  await waitFor(() => expect(post).toHaveBeenCalled());
  expect(await screen.findByRole("textbox", { name: "English HTML" })).toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "German HTML" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Publish versions" })).toBeDisabled();
});

it("shows version history and requires an explicit publication confirmation", async () => {
  get.mockResolvedValue({
    data: [
      {
        id: 1,
        code: "invoice",
        name: "Invoice",
        created_at: "2026-09-23T00:00:00Z",
        versions: [
          {
            id: 2,
            language: "en",
            version: 1,
            status: "draft",
            html: "<h1>Invoice</h1>",
            css: "",
            page_settings: { size: "A4" },
            asset_keys: [],
            created_at: "2026-09-23T00:00:00Z",
            created_by: 1,
            published_at: null,
            published_by: null,
          },
          {
            id: 3,
            language: "de",
            version: 1,
            status: "draft",
            html: "<h1>Rechnung</h1>",
            css: "",
            page_settings: { size: "A4" },
            asset_keys: [],
            created_at: "2026-09-23T00:00:00Z",
            created_by: 1,
            published_at: null,
            published_by: null,
          },
        ],
      },
    ],
    response: new Response(null, { status: 200 }),
  });
  post.mockResolvedValue({
    data: {
      id: 1,
      code: "invoice",
      name: "Invoice",
      created_at: "2026-09-23T00:00:00Z",
      versions: [],
    },
    response: new Response(null, { status: 200 }),
  });
  renderPage();
  expect(await screen.findByText("English v1 — Draft")).toBeInTheDocument();
  expect(screen.getByText("German v1 — Draft")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Publish versions" }));
  expect(screen.getByRole("dialog", { name: "Publish document versions" })).toBeInTheDocument();
  expect(post).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Confirm publication" }));
  await waitFor(() => expect(post).toHaveBeenCalled());
});

it("previews a saved language version with loading, success, and error feedback", async () => {
  get.mockResolvedValue({
    data: [
      {
        id: 1,
        code: "invoice",
        name: "Invoice",
        created_at: "2026-09-23T00:00:00Z",
        versions: [
          {
            id: 2,
            language: "en",
            version: 1,
            status: "draft",
            html: "<h1>Invoice</h1>",
            css: "",
            page_settings: { size: "A4" },
            asset_keys: [],
            created_at: "2026-09-23T00:00:00Z",
            created_by: 1,
            published_at: null,
            published_by: null,
          },
        ],
      },
    ],
    response: new Response(null, { status: 200 }),
  });
  let resolvePreview: ((value: Awaited<ReturnType<typeof post>>) => void) | undefined;
  post.mockImplementation(
    () =>
      new Promise<Awaited<ReturnType<typeof post>>>((resolve) => {
        resolvePreview = resolve;
      }),
  );
  renderPage();
  const button = await screen.findByRole("button", { name: "Preview English PDF" });
  fireEvent.change(screen.getByRole("spinbutton", { name: "Draft invoice ID (optional)" }), {
    target: { value: "42" },
  });
  fireEvent.click(button);
  expect(post).toHaveBeenCalledWith(
    "/api/v1/document-templates/{template_id}/preview/",
    expect.objectContaining({ body: { language: "en", format: "pdf", invoice_id: 42 } }),
  );
  expect(button).toBeDisabled();
  expect(screen.getByRole("status")).toHaveTextContent("Creating preview");
  resolvePreview?.({
    data: { id: "abc", url: "/api/v1/document-previews/abc/", expires_at: "2026-09-23T01:00:00Z" },
    response: new Response(null, { status: 201 }),
  });
  expect(await screen.findByRole("link", { name: "Open English preview" })).toHaveAttribute(
    "href",
    "/api/v1/document-previews/abc/",
  );
  post.mockResolvedValue({
    error: { error: { code: "preview_render_failed", message: "Failed", fields: {} } },
    response: new Response(null, { status: 409 }),
  });
  fireEvent.click(button);
  expect(await screen.findByText("The preview could not be created.")).toBeInTheDocument();
});
