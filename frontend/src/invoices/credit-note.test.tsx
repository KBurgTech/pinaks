import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import { i18n } from "@/i18n";
import { CreditNote } from "./credit-note";

vi.mock("@/api/client", () => ({ apiClient: { POST: vi.fn() } }));
const post = vi.mocked(apiClient.POST);
const invoice = {
  id: 7,
  invoice_type: "STANDARD",
  lifecycle_status: "ISSUED",
  invoice_number: "RE-7",
  lines: [{ position: 1, description: "Service", quantity: "1.0000", unit_price: "100.00" }],
};
beforeEach(() => vi.clearAllMocks());

it.each([
  [
    "en",
    "Create partial credit",
    "Credit reason",
    "Credit quantity: Service",
    "Create credit draft",
  ],
  [
    "de",
    "Teilweise Gutschrift erstellen",
    "Gutschriftgrund",
    "Gutgeschriebene Menge: Service",
    "Gutschriftentwurf erstellen",
  ],
])(
  "requires explicit allocation and reason in %s",
  async (language, action, reason, quantity, confirm) => {
    await i18n.changeLanguage(language);
    post.mockResolvedValue({ data: { id: 8 }, response: new Response() });
    const onOpen = vi.fn();
    render(
      <QueryClientProvider client={new QueryClient()}>
        <CreditNote invoice={invoice} canManage onOpen={onOpen} />
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: action }));
    expect(screen.getByRole("dialog")).toHaveTextContent("RE-7");
    expect(screen.getByRole("button", { name: confirm })).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: reason }), {
      target: { value: "Partial refund" },
    });
    fireEvent.change(screen.getByRole("spinbutton", { name: quantity }), {
      target: { value: "0.5" },
    });
    fireEvent.click(screen.getByRole("button", { name: confirm }));
    await waitFor(() => expect(onOpen).toHaveBeenCalledWith(8));
    expect(post.mock.calls[0]?.[0]).toBe("/api/v1/invoices/{invoice_id}/credit-notes/");
    expect(post.mock.calls[0]?.[1]).toMatchObject({
      body: {
        reason: "Partial refund",
        lines: [{ position: 1, quantity: "0.5", unit_price: "100.00" }],
      },
    });
  },
);

it("hides credit creation for readers and correction documents", async () => {
  await i18n.changeLanguage("en");
  const { rerender } = render(
    <QueryClientProvider client={new QueryClient()}>
      <CreditNote invoice={invoice} canManage={false} onOpen={vi.fn()} />
    </QueryClientProvider>,
  );
  expect(screen.queryByRole("button", { name: "Create partial credit" })).not.toBeInTheDocument();
  rerender(
    <QueryClientProvider client={new QueryClient()}>
      <CreditNote
        invoice={{ ...invoice, invoice_type: "CREDIT_NOTE" }}
        canManage
        onOpen={vi.fn()}
      />
    </QueryClientProvider>,
  );
  expect(screen.queryByRole("button", { name: "Create partial credit" })).not.toBeInTheDocument();
});
