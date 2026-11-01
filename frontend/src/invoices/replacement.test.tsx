import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import { i18n } from "@/i18n";
import { Replacement } from "./replacement";

vi.mock("@/api/client", () => ({ apiClient: { POST: vi.fn() } }));
const post = vi.mocked(apiClient.POST);
const invoice = {
  id: 7,
  invoice_type: "STANDARD",
  lifecycle_status: "CANCELLED",
  invoice_number: "RE-7",
  original_invoice_id: null,
  related_invoice_ids: [8],
  correction_reason: "",
  cancellation_template_id: null,
  grand_total: "119.00",
  currency: "EUR",
  version: 3,
};

beforeEach(() => vi.clearAllMocks());

it.each([
  ["en", "Create replacement", "Replacement reason", "Create replacement draft"],
  ["de", "Ersatzrechnung erstellen", "Korrekturgrund", "Ersatzentwurf erstellen"],
])(
  "confirms the full credit and requires a reason in %s",
  async (language, action, reason, confirm) => {
    await i18n.changeLanguage(language);
    const onOpen = vi.fn();
    const client = new QueryClient();
    client.setQueryData(["invoice", 7], invoice);
    post.mockResolvedValue({ data: { id: 8 }, response: new Response() });
    render(
      <QueryClientProvider client={client}>
        <Replacement invoice={invoice} canManage onOpen={onOpen} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: action }));
    expect(screen.getByRole("dialog")).toHaveTextContent("RE-7");
    expect(screen.getByRole("button", { name: confirm })).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: reason }), {
      target: { value: "Duplicate" },
    });
    fireEvent.click(screen.getByRole("button", { name: confirm }));
    await waitFor(() =>
      expect(post.mock.calls[0]?.[1]).toMatchObject({
        params: { path: { invoice_id: 7 } },
        body: { reason: "Duplicate" },
      }),
    );
    expect(post.mock.calls[0]?.[0]).toBe("/api/v1/invoices/{invoice_id}/correct/");
    expect(post.mock.calls[0]?.[1]).toHaveProperty("body.idempotency_key", expect.any(String));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(8));
    expect(client.getQueryState(["invoice", 7])?.isInvalidated).toBe(true);
  },
);

it("reuses the same command after a network failure", async () => {
  await i18n.changeLanguage("en");
  post.mockRejectedValue(new Error("offline"));
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Replacement invoice={invoice} canManage onOpen={vi.fn()} />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Create replacement" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Replacement reason" }), {
    target: { value: "Fix" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create replacement draft" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Replacement could not be created");
  expect(screen.getByRole("textbox")).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Create replacement draft" }));
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
  expect(post.mock.calls[1]).toEqual(post.mock.calls[0]);
});

it("does not offer replacement for readers or an outstanding original", async () => {
  await i18n.changeLanguage("en");
  const client = new QueryClient();
  const { rerender } = render(
    <QueryClientProvider client={client}>
      <Replacement invoice={invoice} canManage={false} onOpen={vi.fn()} />
    </QueryClientProvider>,
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  rerender(
    <QueryClientProvider client={client}>
      <Replacement
        invoice={{ ...invoice, lifecycle_status: "ISSUED" }}
        canManage
        onOpen={vi.fn()}
      />
    </QueryClientProvider>,
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("issues the saved replacement draft and blocks issuance with unsaved edits", async () => {
  await i18n.changeLanguage("en");
  const client = new QueryClient();
  const draft = {
    ...invoice,
    invoice_type: "REPLACEMENT",
    lifecycle_status: "DRAFT",
    cancellation_template_id: 4,
  };
  post.mockResolvedValue({
    data: { ...draft, lifecycle_status: "ISSUING" },
    response: new Response(),
  });
  const { rerender } = render(
    <QueryClientProvider client={client}>
      <Replacement invoice={draft} canManage onOpen={vi.fn()} hasUnsavedChanges />
    </QueryClientProvider>,
  );
  expect(screen.getByRole("button", { name: "Issue replacement invoice" })).toBeDisabled();
  rerender(
    <QueryClientProvider client={client}>
      <Replacement invoice={draft} canManage onOpen={vi.fn()} />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Issue replacement invoice" }));
  await waitFor(() =>
    expect(post.mock.calls[0]?.[1]).toMatchObject({
      params: { path: { invoice_id: 7 } },
      body: { expected_version: 3, template_id: 4 },
    }),
  );
  expect(post.mock.calls[0]?.[0]).toBe("/api/v1/invoices/{invoice_id}/issue/");
  expect(post.mock.calls[0]?.[1]).toHaveProperty("body.idempotency_key", expect.any(String));
});
