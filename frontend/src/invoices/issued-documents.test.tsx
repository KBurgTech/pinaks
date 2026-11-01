import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import { i18n } from "@/i18n";
import { IssuedDocuments } from "./issued-documents";

vi.mock("@/api/client", () => ({ apiClient: { GET: vi.fn() } }));

it("refreshes original invoice and list caches when related issuance finishes", async () => {
  await i18n.changeLanguage("en");
  vi.mocked(apiClient.GET).mockResolvedValue({
    data: {
      lifecycle_status: "ISSUED",
      operation_state: "completed",
      failure_code: "",
      healthy: true,
      artifacts: [],
    },
    response: new Response(),
  });
  const client = new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } });
  client.setQueryData(["invoice", 6], { id: 6, lifecycle_status: "ISSUED" });
  client.setQueryData(["invoices"], [{ id: 6, lifecycle_status: "ISSUED" }]);
  render(
    <QueryClientProvider client={client}>
      <IssuedDocuments invoiceId={7} />
    </QueryClientProvider>,
  );
  await screen.findByText("Invoice issued. Original documents are available.");
  await waitFor(() => expect(client.getQueryState(["invoice", 6])?.isInvalidated).toBe(true));
  expect(client.getQueryState(["invoices"])?.isInvalidated).toBe(true);
});
