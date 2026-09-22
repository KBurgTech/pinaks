import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import { i18n } from "@/i18n";

import { CustomFields, CustomFieldsAdmin } from "./custom-fields";

vi.mock("@/api/client", () => ({
  apiClient: { GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() },
}));
const get = vi.mocked(apiClient.GET);
const post = vi.mocked(apiClient.POST);
const patch = vi.mocked(apiClient.PATCH);

function renderWithQuery(element: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {element}
    </QueryClientProvider>,
  );
}

const field = {
  id: 1,
  key: "reference",
  target: "customer" as const,
  data_type: "text" as const,
  label_en: "Reference",
  label_de: "Referenz",
  help_en: "Customer code",
  help_de: "Kundencode",
  required: false,
  search_mode: "exact" as const,
  visibility: "internal" as const,
  is_sensitive: false,
  is_retired: false,
  display_order: 0,
  choices: [],
};

beforeEach(async () => {
  vi.clearAllMocks();
  await i18n.changeLanguage("en");
  get.mockResolvedValue({ data: [field], response: new Response(null, { status: 200 }) });
});

it("renders localized dynamic fields and emits typed values", async () => {
  const change = vi.fn();
  const view = renderWithQuery(<CustomFields target="customer" values={{}} onChange={change} />);
  expect(await screen.findByLabelText("Reference")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Reference"), { target: { value: "R-1" } });
  expect(change).toHaveBeenCalledWith({ reference: "R-1" });
  await i18n.changeLanguage("de");
  view.rerender(
    <QueryClientProvider client={new QueryClient()}>
      <CustomFields target="customer" values={{}} onChange={change} />
    </QueryClientProvider>,
  );
  expect(await screen.findByLabelText("Referenz")).toBeInTheDocument();
});

it("lets an Admin publish bilingual definitions", async () => {
  get.mockResolvedValue({ data: [], response: new Response(null, { status: 200 }) });
  post.mockResolvedValue({ data: field, response: new Response(null, { status: 201 }) });
  renderWithQuery(<CustomFieldsAdmin />);
  fireEvent.change(await screen.findByLabelText("Machine key"), { target: { value: "reference" } });
  fireEvent.change(screen.getByLabelText("English label"), { target: { value: "Reference" } });
  fireEvent.change(screen.getByLabelText("German label"), { target: { value: "Referenz" } });
  fireEvent.click(screen.getByRole("button", { name: "Publish field" }));
  await waitFor(() => expect(post).toHaveBeenCalled());
  expect(post.mock.calls[0]?.[1]).toMatchObject({
    body: { key: "reference", label_en: "Reference", label_de: "Referenz" },
  });
});

it("publishes typed integer defaults", async () => {
  get.mockResolvedValue({ data: [], response: new Response(null, { status: 200 }) });
  post.mockResolvedValue({ data: field, response: new Response(null, { status: 201 }) });
  renderWithQuery(<CustomFieldsAdmin />);
  fireEvent.change(await screen.findByLabelText("Machine key"), { target: { value: "visits" } });
  fireEvent.change(screen.getByLabelText("English label"), { target: { value: "Visits" } });
  fireEvent.change(screen.getByLabelText("German label"), { target: { value: "Besuche" } });
  fireEvent.change(screen.getByLabelText("Data type"), { target: { value: "integer" } });
  fireEvent.change(screen.getByLabelText("Default value"), { target: { value: "3" } });
  fireEvent.click(screen.getByRole("button", { name: "Publish field" }));
  await waitFor(() => expect(post).toHaveBeenCalled());
  expect(post.mock.calls[0]?.[1]).toMatchObject({ body: { default_value: 3 } });
});

it("lets an Admin edit bilingual labels without changing the machine key", async () => {
  get.mockResolvedValue({ data: [field], response: new Response(null, { status: 200 }) });
  patch.mockResolvedValue({
    data: { ...field, label_de: "Kennung" },
    response: new Response(null, { status: 200 }),
  });
  renderWithQuery(<CustomFieldsAdmin />);
  fireEvent.click(await screen.findByRole("button", { name: "Edit" }));
  expect(screen.getByLabelText("Machine key")).toBeDisabled();
  fireEvent.change(screen.getByLabelText("German label"), { target: { value: "Kennung" } });
  fireEvent.click(screen.getByRole("button", { name: "Save field" }));
  await waitFor(() => expect(patch).toHaveBeenCalled());
  expect(patch.mock.calls[0]?.[1]).toMatchObject({ body: { label_de: "Kennung" } });
});
