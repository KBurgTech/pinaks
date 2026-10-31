import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import { i18n } from "@/i18n";
import { Cancellation } from "./cancellation";

vi.mock("@/api/client", () => ({ apiClient: { POST: vi.fn() } }));
const post = vi.mocked(apiClient.POST);
const invoice = {
  id: 7,
  invoice_type: "STANDARD",
  lifecycle_status: "ISSUED",
  invoice_number: "RE-7",
  original_invoice_id: null,
  related_invoice_ids: [],
  correction_reason: "",
  cancellation_template_id: null,
  grand_total: "119.00",
  currency: "EUR",
  version: 3,
};

beforeEach(() => vi.clearAllMocks());

it.each([
  ["en", "Cancel invoice", "Cancellation reason", "Create cancellation draft"],
  ["de", "Rechnung stornieren", "Stornogrund", "Stornoentwurf erstellen"],
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
        <Cancellation invoice={invoice} canManage onOpen={onOpen} />
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
    expect(post.mock.calls[0]?.[0]).toBe("/api/v1/invoices/{invoice_id}/cancel/");
    expect(post.mock.calls[0]?.[1]).toHaveProperty("body.idempotency_key", expect.any(String));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(8));
    expect(client.getQueryState(["invoice", 7])?.isInvalidated).toBe(true);
  },
);

it("keeps the command identity on retry and shows a localized error", async () => {
  await i18n.changeLanguage("en");
  post.mockRejectedValue(new Error("offline"));
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Cancellation invoice={invoice} canManage onOpen={vi.fn()} />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Cancel invoice" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Cancellation reason" }), {
    target: { value: "Duplicate" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Create cancellation draft" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Cancellation could not be completed.",
  );
  fireEvent.click(screen.getByRole("button", { name: "Create cancellation draft" }));
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
  expect(post.mock.calls[1]).toEqual(post.mock.calls[0]);
});

it("shows relationship navigation to readers without mutation controls", async () => {
  await i18n.changeLanguage("en");
  const onOpen = vi.fn();
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Cancellation
        invoice={{ ...invoice, related_invoice_ids: [8], lifecycle_status: "CANCELLED" }}
        canManage={false}
        onOpen={onOpen}
      />
    </QueryClientProvider>,
  );
  expect(screen.queryByRole("button", { name: "Cancel invoice" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Related document #8" }));
  expect(onOpen).toHaveBeenCalledWith(8);
});

it("issues the unchanged cancellation draft using the original template", async () => {
  await i18n.changeLanguage("en");
  const client = new QueryClient();
  post.mockResolvedValue({
    data: { ...invoice, lifecycle_status: "ISSUING" },
    response: new Response(),
  });
  render(
    <QueryClientProvider client={client}>
      <Cancellation
        invoice={{
          ...invoice,
          invoice_type: "CANCELLATION",
          lifecycle_status: "DRAFT",
          original_invoice_id: 6,
          correction_reason: "Duplicate",
          cancellation_template_id: 2,
        }}
        canManage
        onOpen={vi.fn()}
      />
    </QueryClientProvider>,
  );
  expect(screen.getByText("Duplicate")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Issue cancellation invoice" }));
  await waitFor(() =>
    expect(post.mock.calls[0]?.[1]).toMatchObject({
      params: { path: { invoice_id: 7 } },
      body: { expected_version: 3, template_id: 2 },
    }),
  );
  expect(post.mock.calls[0]?.[0]).toBe("/api/v1/invoices/{invoice_id}/issue/");
  expect(post.mock.calls[0]?.[1]).toHaveProperty("body.idempotency_key", expect.any(String));
  await waitFor(() =>
    expect(client.getQueryData(["invoice", 7])).toMatchObject({ lifecycle_status: "ISSUING" }),
  );
});

it.each([
  ["en", "Issue credit note"],
  ["de", "Gutschrift ausstellen"],
])("reviews and issues a server-calculated credit draft in %s", async (language, action) => {
  await i18n.changeLanguage(language);
  post.mockResolvedValue({
    data: { ...invoice, lifecycle_status: "ISSUING" },
    response: new Response(),
  });
  render(
    <QueryClientProvider client={new QueryClient()}>
      <Cancellation
        invoice={{
          ...invoice,
          invoice_type: "CREDIT_NOTE",
          lifecycle_status: "DRAFT",
          original_invoice_id: 6,
          correction_reason: "Partial refund",
          cancellation_template_id: 2,
          grand_total: "59.50",
        }}
        canManage
        onOpen={vi.fn()}
      />
    </QueryClientProvider>,
  );
  expect(screen.getByText("Partial refund")).toBeInTheDocument();
  expect(
    screen.getByRole("region", { name: language === "de" ? "Gutschrift" : "Credit note" }),
  ).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Cancel invoice" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: action }));
  await waitFor(() => expect(post).toHaveBeenCalled());
  expect(post.mock.calls[0]?.[0]).toBe("/api/v1/invoices/{invoice_id}/issue/");
  expect(post.mock.calls[0]?.[1]).toMatchObject({ body: { expected_version: 3, template_id: 2 } });
});
