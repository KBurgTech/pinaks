import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import { i18n } from "@/i18n";
import { PaymentStatus } from "./payment-status";

vi.mock("@/api/client", () => ({ apiClient: { POST: vi.fn() } }));
const post = vi.mocked(apiClient.POST);
const invoice = { id: 7, lifecycle_status: "ISSUED", payment_status: "UNPAID", is_overdue: true };

beforeEach(() => {
  vi.clearAllMocks();
});

it.each([
  ["en", "Overdue", "Mark paid"],
  ["de", "Überfällig", "Als bezahlt markieren"],
])("shows backend status and submits payment command in %s", async (language, status, action) => {
  await i18n.changeLanguage(language);
  post.mockResolvedValue({
    data: { ...invoice, payment_status: "PAID", is_overdue: false },
    response: new Response(),
  });
  const client = new QueryClient();
  client.setQueryData(["invoice", 7], invoice);
  render(
    <QueryClientProvider client={client}>
      <PaymentStatus invoice={invoice} canManage />
    </QueryClientProvider>,
  );
  expect(screen.getByText(status)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: action }));
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("/api/v1/invoices/{invoice_id}/mark-paid/", {
      params: { path: { invoice_id: 7 } },
    }),
  );
  await waitFor(() =>
    expect(client.getQueryData(["invoice", 7])).toMatchObject({ payment_status: "PAID" }),
  );
});

it.each(["DRAFT", "ISSUING", "CANCELLED"])(
  "offers no payment command for %s",
  async (lifecycle) => {
    await i18n.changeLanguage("en");
    render(
      <QueryClientProvider client={new QueryClient()}>
        <PaymentStatus invoice={{ ...invoice, lifecycle_status: lifecycle }} canManage />
      </QueryClientProvider>,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  },
);

it("shows paid status without actions to readers", async () => {
  await i18n.changeLanguage("en");
  render(
    <QueryClientProvider client={new QueryClient()}>
      <PaymentStatus
        invoice={{ ...invoice, payment_status: "PAID", is_overdue: false }}
        canManage={false}
      />
    </QueryClientProvider>,
  );
  expect(screen.getByText("Paid")).toBeInTheDocument();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("keeps status and exposes a localized error on failure", async () => {
  await i18n.changeLanguage("en");
  post.mockRejectedValue(new Error("offline"));
  render(
    <QueryClientProvider client={new QueryClient()}>
      <PaymentStatus
        invoice={{ ...invoice, payment_status: "PAID", is_overdue: false }}
        canManage
      />
    </QueryClientProvider>,
  );
  fireEvent.click(screen.getByRole("button", { name: "Mark unpaid" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Payment status could not be updated.",
  );
  expect(screen.getByText("Paid")).toBeInTheDocument();
});
