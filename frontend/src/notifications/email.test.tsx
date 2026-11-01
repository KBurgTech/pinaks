import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { apiClient } from "@/api/client";
import { i18n } from "@/i18n";
import { InvoiceEmail } from "./invoice-email";
import { EmailTemplatePage } from "./template-page";

vi.mock("@/api/client", () => ({ apiClient: { GET: vi.fn(), POST: vi.fn() } }));
const get = vi.mocked(apiClient.GET);
const post = vi.mocked(apiClient.POST);
function mount(component: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {component}
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
});

it.each([
  ["en", "Send invoice email", "Recipients", "Language", "Queue email", "Email queued.", "Close"],
  [
    "de",
    "Rechnung per E-Mail senden",
    "Empfänger",
    "Sprache",
    "E-Mail einreihen",
    "E-Mail eingereiht.",
    "Schließen",
  ],
])(
  "queues a snapshot with correspondence defaults and restores focus in %s",
  async (language, trigger, recipients, label, submit, success, close) => {
    await i18n.changeLanguage(language);
    get.mockResolvedValue({
      data: {
        language: "de",
        recipients: ["payer@example.test"],
        templates: [{ id: 3, name: "Invoice" }],
      },
      response: new Response(),
    });
    post.mockResolvedValue({
      data: { id: "email-1", delivery_state: "queued" },
      response: new Response(),
    });
    mount(<InvoiceEmail invoiceId={7} lifecycle="ISSUED" canSend />);
    const button = screen.getByRole("button", { name: trigger });
    fireEvent.click(button);
    expect(await screen.findByLabelText(recipients)).toHaveValue("payer@example.test");
    expect(screen.getByLabelText(label)).toHaveValue("de");
    fireEvent.click(screen.getByRole("button", { name: submit }));
    await screen.findByText(success);
    const identity: unknown = expect.any(String);
    expect(post).toHaveBeenCalledWith("/api/v1/invoices/{invoice_id}/send/", {
      params: { path: { invoice_id: 7 } },
      body: {
        template_id: 3,
        language: "de",
        recipients: ["payer@example.test"],
        idempotency_key: identity,
      },
    });
    expect(screen.getByRole("button", { name: submit })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: close }));
    await waitFor(() => expect(button).toHaveFocus());
  },
);

it("reuses identity after a network failure and shows an error", async () => {
  await i18n.changeLanguage("en");
  get.mockResolvedValue({
    data: {
      language: "en",
      recipients: ["payer@example.test"],
      templates: [{ id: 3, name: "Invoice" }],
    },
    response: new Response(),
  });
  post.mockRejectedValue(new Error("offline"));
  mount(<InvoiceEmail invoiceId={7} lifecycle="ISSUED" canSend />);
  fireEvent.click(screen.getByRole("button", { name: "Send invoice email" }));
  const submit = await screen.findByRole("button", { name: "Queue email" });
  await waitFor(() => expect(submit).toBeEnabled());
  fireEvent.click(submit);
  expect(await screen.findByRole("alert")).toHaveTextContent("Email could not be queued.");
  fireEvent.click(submit);
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
  expect(post.mock.calls[0]).toEqual(post.mock.calls[1]);
});

it.each([
  [false, "ISSUED"],
  [true, "DRAFT"],
  [true, "ISSUING"],
])("hides unavailable send actions", (canSend, lifecycle) => {
  mount(<InvoiceEmail invoiceId={7} lifecycle={String(lifecycle)} canSend={Boolean(canSend)} />);
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(get).not.toHaveBeenCalled();
});

it.each([
  ["en", "Email templates", "Code", "Name", "Create template"],
  ["de", "E-Mail-Vorlagen", "Code", "Name", "Vorlage erstellen"],
])("creates templates in %s", async (language, heading, code, name, create) => {
  await i18n.changeLanguage(language);
  get.mockResolvedValue({ data: [], response: new Response() });
  post.mockResolvedValue({
    data: { id: 1, code: "invoice", name: "Invoice", versions: [] },
    response: new Response(),
  });
  mount(<EmailTemplatePage />);
  expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText(code), { target: { value: "invoice" } });
  fireEvent.change(screen.getByLabelText(name), { target: { value: "Invoice" } });
  fireEvent.click(screen.getByRole("button", { name: create }));
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("/api/v1/email-templates/", {
      body: { code: "invoice", name: "Invoice" },
    }),
  );
});

it("creates language versions and publishes a template", async () => {
  await i18n.changeLanguage("en");
  get.mockResolvedValue({
    data: [{ id: 3, code: "invoice", name: "Invoice", versions: [] }],
    response: new Response(),
  });
  post.mockResolvedValue({ data: { id: 1 }, response: new Response() });
  mount(<EmailTemplatePage />);
  await screen.findByRole("heading", { name: "Invoice" });
  fireEvent.change(screen.getByLabelText("Subject"), {
    target: { value: "Invoice {{ invoice_number }}" },
  });
  fireEvent.change(screen.getByLabelText("Body"), { target: { value: "Attached." } });
  fireEvent.click(screen.getByRole("button", { name: "Save new version" }));
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("/api/v1/email-templates/{template_id}/versions/", {
      params: { path: { template_id: 3 } },
      body: { language: "en", subject: "Invoice {{ invoice_number }}", body: "Attached." },
    }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Publish both languages" })).toBeEnabled(),
  );
  fireEvent.click(screen.getByRole("button", { name: "Publish both languages" }));
  await waitFor(() =>
    expect(post).toHaveBeenCalledWith("/api/v1/email-templates/{template_id}/publish/", {
      params: { path: { template_id: 3 } },
    }),
  );
});

it("preserves a command identity when a failed dialog is closed and reopened", async () => {
  await i18n.changeLanguage("en");
  get.mockResolvedValue({
    data: {
      language: "en",
      recipients: ["a@example.test"],
      templates: [{ id: 3, name: "Invoice" }],
    },
    response: new Response(),
  });
  post.mockRejectedValue(new Error("lost response"));
  mount(<InvoiceEmail invoiceId={7} lifecycle="ISSUED" canSend />);
  fireEvent.click(screen.getByRole("button", { name: "Send invoice email" }));
  let submit = await screen.findByRole("button", { name: "Queue email" });
  fireEvent.click(submit);
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  fireEvent.click(screen.getByRole("button", { name: "Send invoice email" }));
  submit = await screen.findByRole("button", { name: "Queue email" });
  fireEvent.click(submit);
  await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
  expect(post.mock.calls[0]).toEqual(post.mock.calls[1]);
});

it.each([
  ["en", "Email delivery", "Sent", "Outcome unknown — check delivery before sending again."],
  [
    "de",
    "E-Mail-Zustellung",
    "Gesendet",
    "Ergebnis unbekannt — Zustellung vor erneutem Senden prüfen.",
  ],
])(
  "shows delivery history and ambiguous handoff in %s",
  async (language, heading, sent, unknown) => {
    await i18n.changeLanguage(language);
    get.mockImplementation((path) =>
      Promise.resolve({
        data:
          path === "/api/v1/invoices/{invoice_id}/emails/"
            ? [
                {
                  id: "1",
                  delivery_state: "sent",
                  language: "en",
                  created_at: "2026-11-01T10:00:00Z",
                  next_attempt_at: null,
                  attempts: [
                    {
                      id: 1,
                      started_at: "2026-11-01T10:00:00Z",
                      finished_at: "2026-11-01T10:00:01Z",
                      outcome: "sent",
                      failure_code: "",
                      response_code: 250,
                    },
                  ],
                },
                {
                  id: "2",
                  delivery_state: "failed",
                  language: "de",
                  created_at: "2026-11-01T11:00:00Z",
                  next_attempt_at: null,
                  attempts: [
                    {
                      id: 2,
                      started_at: "2026-11-01T11:00:00Z",
                      finished_at: "2026-11-01T11:00:01Z",
                      outcome: "unknown",
                      failure_code: "delivery_unknown",
                      response_code: null,
                    },
                  ],
                },
              ]
            : { language: "en", recipients: [], templates: [] },
        response: new Response(),
      }),
    );
    mount(<InvoiceEmail invoiceId={7} lifecycle="ISSUED" canSend />);
    expect(await screen.findByRole("heading", { name: heading })).toBeInTheDocument();
    expect(await screen.findAllByText(sent)).not.toHaveLength(0);
    expect(screen.getByText(unknown)).toBeInTheDocument();
  },
);
