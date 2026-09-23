import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { CustomFields } from "@/custom-fields/custom-fields";
import { loadDefinitions } from "@/custom-fields/definitions";
import { DataTable, Field, PageHeader, Status } from "@/ui/primitives";
import type { components } from "@/api/generated/schema";

type Invoice = components["schemas"]["Invoice"];
type Customer = components["schemas"]["Customer"];
type CatalogItem = components["schemas"]["CatalogItem"];
type Recipient = components["schemas"]["BillingRecipient"];
type Line = components["schemas"]["InvoiceLine"];
type Preset = components["schemas"]["Preset"];
type PresetLine = components["schemas"]["PresetLineRequest"];
type LineOperation = components["schemas"]["LineOperationRequest"];
type Update = components["schemas"]["PatchedDraftUpdateRequest"];
type RecipientInput = components["schemas"]["RecipientInputRequest"];
type ErrorFields = components["schemas"]["ErrorBody"]["fields"];
type Mode = "list" | "new" | "detail";
type RecipientSource = RecipientInput["source"];

const inputClass =
  "w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 disabled:bg-neutral-100";
const buttonClass =
  "rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm font-medium hover:bg-neutral-100 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50";
const primaryClass =
  "rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white hover:bg-neutral-700 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50";

function asCustomData(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function isInvoice(value: unknown): value is Invoice {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "number" &&
    "version" in value &&
    typeof value.version === "number" &&
    "grand_total" in value &&
    typeof value.grand_total === "string" &&
    "lines" in value &&
    Array.isArray(value.lines)
  );
}

function serverError(error: unknown): { code: string; fields: ErrorFields } {
  if (typeof error === "object" && error !== null && "error" in error) {
    const body = error.error;
    if (
      typeof body === "object" &&
      body !== null &&
      "code" in body &&
      typeof body.code === "string"
    ) {
      return {
        code: body.code,
        fields:
          "fields" in body && typeof body.fields === "object" && body.fields !== null
            ? (body.fields as ErrorFields)
            : {},
      };
    }
  }
  return { code: "unknown", fields: {} };
}

async function fetchInvoices(
  page: number,
  filter: { field: string; operator: string; value: string } | null,
): Promise<components["schemas"]["PaginatedInvoiceList"]> {
  const { data } = await apiClient.GET("/api/v1/invoices/", {
    params: {
      query: {
        page,
        page_size: 25,
        ...(filter?.field.startsWith("invoice_line:")
          ? {
              line_custom_field: filter.field.slice("invoice_line:".length),
              line_custom_operator: filter.operator,
              line_custom_value: filter.value,
            }
          : filter
            ? {
                custom_field: filter.field,
                custom_operator: filter.operator,
                custom_value: filter.value,
              }
            : {}),
      },
    },
  });
  const rows: unknown = data?.results;
  if (data && Array.isArray(rows) && rows.every(isInvoice)) {
    return { count: data.count, next: data.next, previous: data.previous, results: rows };
  }
  throw new Error("invoices_unavailable");
}

async function fetchInvoice(id: number): Promise<Invoice> {
  const { data } = await apiClient.GET("/api/v1/invoices/{invoice_id}/", {
    params: { path: { invoice_id: id } },
  });
  if (isInvoice(data)) return data;
  throw new Error("invoice_unavailable");
}

async function fetchCustomers(): Promise<readonly Customer[]> {
  const { data } = await apiClient.GET("/api/v1/customers/", {
    params: { query: { search: "", archived: false, page: 1, page_size: 100 } },
  });
  const rows: unknown = data?.results;
  if (
    Array.isArray(rows) &&
    rows.every(
      (value: unknown): value is Customer =>
        typeof value === "object" &&
        value !== null &&
        "id" in value &&
        typeof value.id === "number" &&
        "display_name" in value &&
        typeof value.display_name === "string",
    )
  )
    return rows;
  throw new Error("customers_unavailable");
}

async function fetchCatalog(): Promise<readonly CatalogItem[]> {
  const { data } = await apiClient.GET("/api/v1/catalog/", {
    params: { query: { search: "", archived: false, page: 1, page_size: 100 } },
  });
  const rows: unknown = data?.results;
  if (
    Array.isArray(rows) &&
    rows.every(
      (value: unknown): value is CatalogItem =>
        typeof value === "object" &&
        value !== null &&
        "id" in value &&
        typeof value.id === "number" &&
        "code" in value &&
        typeof value.code === "string",
    )
  )
    return rows;
  throw new Error("catalog_unavailable");
}

async function fetchRecipients(customerId: number): Promise<readonly Recipient[]> {
  const { data } = await apiClient.GET("/api/v1/customers/{customer_id}/billing-recipients/", {
    params: { path: { customer_id: customerId } },
  });
  const rows: unknown = data;
  if (
    Array.isArray(rows) &&
    rows.every(
      (value: unknown): value is Recipient =>
        typeof value === "object" &&
        value !== null &&
        "id" in value &&
        typeof value.id === "number" &&
        "display_name" in value &&
        typeof value.display_name === "string",
    )
  )
    return rows;
  throw new Error("recipients_unavailable");
}

function initialRoute(): { mode: Mode; id: number | null } {
  const path = window.location.pathname;
  const match = /^\/app\/invoices\/(\d+)\/?$/.exec(path);
  if (match) return { mode: "detail", id: Number(match[1]) };
  return {
    mode: path === "/app/invoices/new" || path === "/app/invoices/new/" ? "new" : "list",
    id: null,
  };
}

function formatTotal(amount: string, currency: string) {
  return amount + " " + currency;
}

export function InvoicePage({
  canMutate,
  canAdminister = false,
}: {
  canMutate: boolean;
  canAdminister?: boolean;
}) {
  const { t, i18n } = useTranslation("shell");
  const [route, setRoute] = useState(initialRoute);
  const [page, setPage] = useState(1);
  const [filterField, setFilterField] = useState("");
  const [filterValue, setFilterValue] = useState("");
  const [filterOperator, setFilterOperator] = useState("exact");
  const [appliedFilter, setAppliedFilter] = useState<{
    field: string;
    operator: string;
    value: string;
  } | null>(null);
  const invoiceFields = useQuery({
    queryKey: ["custom-fields", "invoice"],
    queryFn: () => loadDefinitions("invoice"),
  });
  const lineFields = useQuery({
    queryKey: ["custom-fields", "invoice_line"],
    queryFn: () => loadDefinitions("invoice_line"),
  });
  const searchableFields = [
    ...(invoiceFields.data ?? []).map((field) => ({ ...field, filterKey: field.key })),
    ...(lineFields.data ?? []).map((field) => ({
      ...field,
      filterKey: `invoice_line:${field.key}`,
    })),
  ].filter((field) => !field.is_sensitive && field.search_mode !== "none");
  const [customerId, setCustomerId] = useState("");
  const [newCustomData, setNewCustomData] = useState<Record<string, unknown>>({});
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);
  const clients = useQueryClient();
  const invoices = useQuery({
    queryKey: ["invoices", page, appliedFilter],
    queryFn: () => fetchInvoices(page, appliedFilter),
    enabled: route.mode === "list",
  });
  const customers = useQuery({
    queryKey: ["invoice-customers"],
    queryFn: fetchCustomers,
    enabled: route.mode !== "detail",
  });
  const detail = useQuery({
    queryKey: ["invoice", route.id],
    queryFn: () => fetchInvoice(route.id!),
    enabled: route.mode === "detail" && route.id !== null,
  });

  function navigate(mode: Mode, id: number | null = null) {
    const path =
      mode === "detail"
        ? "/app/invoices/" + id + "/"
        : mode === "new"
          ? "/app/invoices/new"
          : "/app/invoices/";
    window.history.pushState({}, "", path);
    setRoute({ mode, id });
  }

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = Number(customerId);
    if (!Number.isInteger(parsed) || parsed <= 0) {
      setCreateError(t("invoicePage.required"));
      return;
    }
    setCreating(true);
    setCreateError("");
    try {
      const result = await apiClient.POST("/api/v1/invoices/", {
        body: {
          customer_id: parsed,
          ...(Object.keys(newCustomData).length ? { custom_data: newCustomData } : {}),
        },
      });
      if (isInvoice(result.data)) {
        clients.setQueryData(["invoice", result.data.id], result.data);
        await clients.invalidateQueries({ queryKey: ["invoices"] });
        navigate("detail", result.data.id);
      } else {
        setCreateError(
          Object.values(serverError(result.error).fields).flat()[0]?.message ??
            t("invoicePage.saveError"),
        );
      }
    } catch {
      setCreateError(t("invoicePage.saveError"));
    } finally {
      setCreating(false);
    }
  }

  if (route.mode === "list") {
    return (
      <>
        <PageHeader title={t("invoicePage.heading")}>
          {canMutate && (
            <button className={primaryClass} onClick={() => navigate("new")} type="button">
              {t("invoicePage.new")}
            </button>
          )}
        </PageHeader>
        {searchableFields.length > 0 && (
          <form
            className="mb-4 flex flex-wrap items-end gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (filterField && filterValue) {
                setPage(1);
                setAppliedFilter({
                  field: filterField,
                  operator: filterOperator,
                  value: filterValue,
                });
              }
            }}
          >
            <Field inputId="invoice-custom-filter" label={t("invoicePage.customFilter")}>
              <select
                className={inputClass}
                id="invoice-custom-filter"
                value={filterField}
                onChange={(event) => {
                  const field = searchableFields.find(
                    (item) => item.filterKey === event.target.value,
                  );
                  setFilterField(event.target.value);
                  setFilterOperator(
                    field?.search_mode === "range"
                      ? "gte"
                      : field?.search_mode === "text"
                        ? "text"
                        : "exact",
                  );
                }}
              >
                <option value="">—</option>
                {searchableFields.map((field) => (
                  <option key={field.filterKey} value={field.filterKey}>
                    {i18n.resolvedLanguage === "de" ? field.label_de : field.label_en}
                  </option>
                ))}
              </select>
            </Field>
            {searchableFields.find((field) => field.filterKey === filterField)?.search_mode ===
              "range" && (
              <Field inputId="invoice-custom-operator" label={t("invoicePage.filterOperator")}>
                <select
                  className={inputClass}
                  id="invoice-custom-operator"
                  value={filterOperator}
                  onChange={(event) => setFilterOperator(event.target.value)}
                >
                  <option value="gte">≥</option>
                  <option value="lte">≤</option>
                </select>
              </Field>
            )}
            <Field inputId="invoice-custom-value" label={t("invoicePage.filterValue")}>
              <input
                className={inputClass}
                id="invoice-custom-value"
                value={filterValue}
                onChange={(event) => setFilterValue(event.target.value)}
              />
            </Field>
            <button className={buttonClass} type="submit">
              {t("invoicePage.filterApply")}
            </button>
            {appliedFilter && (
              <button
                className={buttonClass}
                type="button"
                onClick={() => {
                  setAppliedFilter(null);
                  setPage(1);
                }}
              >
                {t("invoicePage.filterClear")}
              </button>
            )}
          </form>
        )}
        {invoices.isPending ? (
          <p role="status">{t("invoicePage.loading")}</p>
        ) : invoices.isError ? (
          <p role="alert">{t("invoicePage.loadError")}</p>
        ) : invoices.data.results.length === 0 ? (
          <p>{t("invoicePage.empty")}</p>
        ) : (
          <>
            <DataTable caption={t("invoicePage.heading")}>
              <thead>
                <tr>
                  <th scope="col">{t("invoicePage.customer")}</th>
                  <th scope="col">{t("invoicePage.issueDate")}</th>
                  <th scope="col">{t("invoicePage.status")}</th>
                  <th scope="col">{t("invoicePage.total")}</th>
                  <th scope="col">{t("invoicePage.actions")}</th>
                </tr>
              </thead>
              <tbody>
                {invoices.data.results.map((item) => (
                  <tr key={item.id}>
                    <td>{item.customer_id}</td>
                    <td>{item.issue_date}</td>
                    <td>
                      <Status>{item.lifecycle_status}</Status>
                    </td>
                    <td>{formatTotal(item.grand_total, item.currency)}</td>
                    <td>
                      <button
                        className={buttonClass}
                        onClick={() => navigate("detail", item.id)}
                        type="button"
                      >
                        {t("invoicePage.open")}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
            <nav aria-label={t("invoicePage.heading")} className="mt-4 flex gap-2">
              <button
                className={buttonClass}
                disabled={!invoices.data.previous}
                onClick={() => setPage(page - 1)}
                type="button"
              >
                {t("invoicePage.pagePrevious")}
              </button>
              <button
                className={buttonClass}
                disabled={!invoices.data.next}
                onClick={() => setPage(page + 1)}
                type="button"
              >
                {t("invoicePage.pageNext")}
              </button>
            </nav>
          </>
        )}
        {!canMutate && <p className="mt-4 text-sm text-neutral-600">{t("invoicePage.readOnly")}</p>}
      </>
    );
  }

  if (route.mode === "new") {
    return (
      <>
        <PageHeader title={t("invoicePage.new")} />
        <button className={buttonClass} onClick={() => navigate("list")} type="button">
          {t("invoicePage.back")}
        </button>
        {customers.isPending ? (
          <p role="status">{t("invoicePage.loading")}</p>
        ) : customers.isError ? (
          <p role="alert">{t("invoicePage.loadError")}</p>
        ) : (
          <form className="mt-6 grid max-w-md gap-4" onSubmit={(event) => void create(event)}>
            <Field
              inputId="draft-customer"
              label={t("invoicePage.customer")}
              error={createError || undefined}
            >
              <select
                className={inputClass}
                id="draft-customer"
                onChange={(event) => setCustomerId(event.target.value)}
                required
                value={customerId}
              >
                <option value="">{t("invoicePage.selectCustomer")}</option>
                {customers.data
                  .filter((item) => !item.is_archived)
                  .map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.customer_number + " — " + item.display_name}
                    </option>
                  ))}
              </select>
            </Field>
            <CustomFields
              target="invoice"
              values={newCustomData}
              showSensitive={canAdminister}
              onChange={setNewCustomData}
            />
            {createError && (
              <p role="alert" className="text-sm text-red-700">
                {createError}
              </p>
            )}
            {canMutate ? (
              <button className={primaryClass} disabled={creating} type="submit">
                {t("invoicePage.create")}
              </button>
            ) : (
              <p>{t("invoicePage.readOnly")}</p>
            )}
          </form>
        )}
      </>
    );
  }

  return detail.isPending ? (
    <p role="status">{t("invoicePage.loading")}</p>
  ) : detail.isError ? (
    <p role="alert">{t("invoicePage.loadError")}</p>
  ) : (
    <DraftEditor
      key={detail.data.id + ":" + detail.data.version}
      canMutate={canMutate}
      canAdminister={canAdminister}
      invoice={detail.data}
      onBack={() => navigate("list")}
      onSaved={(updated) => {
        clients.setQueryData(["invoice", updated.id], updated);
        void clients.invalidateQueries({ queryKey: ["invoices"] });
      }}
      onReload={() => void detail.refetch()}
    />
  );
}

type DraftValues = {
  document_language: "en" | "de";
  issue_date: string;
  due_date: string;
  recipientSource: RecipientSource;
  recipientId: string;
  sourceCustomerId: string;
  party_type: "person" | "organization";
  given_name: string;
  family_name: string;
  organization_name: string;
  email: string;
  phone: string;
  address_line_1: string;
  address_line_2: string;
  postal_code: string;
  city: string;
  country_code: string;
};

function valuesFromInvoice(invoice: Invoice): DraftValues {
  const recipient = invoice.recipient;
  const field = (name: string) => (typeof recipient[name] === "string" ? recipient[name] : "");
  return {
    document_language: invoice.document_language === "de" ? "de" : "en",
    issue_date: invoice.issue_date,
    due_date: invoice.due_date ?? "",
    recipientSource: typeof recipient["party_type"] === "string" ? "manual" : "customer",
    recipientId: "",
    sourceCustomerId: "",
    party_type: field("party_type") === "organization" ? "organization" : "person",
    given_name: field("given_name"),
    family_name: field("family_name"),
    organization_name: field("organization_name"),
    email: field("email"),
    phone: field("phone"),
    address_line_1: field("address_line_1"),
    address_line_2: field("address_line_2"),
    postal_code: field("postal_code"),
    city: field("city"),
    country_code: field("country_code") || "DE",
  };
}

function recipientInput(values: DraftValues): RecipientInput {
  switch (values.recipientSource) {
    case "saved":
      return { source: "saved", recipient_id: Number(values.recipientId) };
    case "known_customer":
      return { source: "known_customer", customer_id: Number(values.sourceCustomerId) };
    case "manual":
      return {
        source: "manual",
        values: {
          party_type: values.party_type,
          given_name: values.given_name,
          family_name: values.family_name,
          organization_name: values.organization_name,
          email: values.email,
          phone: values.phone,
          address_line_1: values.address_line_1,
          address_line_2: values.address_line_2,
          postal_code: values.postal_code,
          city: values.city,
          country_code: values.country_code,
        },
      };
    default:
      return { source: "customer" };
  }
}

function DraftEditor({
  invoice,
  canMutate,
  canAdminister,
  onSaved,
  onBack,
  onReload,
}: {
  invoice: Invoice;
  canMutate: boolean;
  canAdminister: boolean;
  onSaved: (invoice: Invoice) => void;
  onBack: () => void;
  onReload: () => void;
}) {
  const { t } = useTranslation("shell");
  const [values, setValues] = useState(() => valuesFromInvoice(invoice));
  const [customData, setCustomData] = useState<Record<string, unknown>>(
    asCustomData(invoice.custom_data),
  );
  const [dirty, setDirty] = useState(false);
  const [recipientDirty, setRecipientDirty] = useState(false);
  const [error, setError] = useState("");
  const [fields, setFields] = useState<ErrorFields>({});
  const [conflict, setConflict] = useState(false);
  const [saving, setSaving] = useState(false);
  const [success, setSuccess] = useState(false);
  const [lineMode, setLineMode] = useState<"none" | "manual" | "catalog" | "edit">("none");
  const [editingLine, setEditingLine] = useState<Line | null>(null);
  const customers = useQuery({ queryKey: ["invoice-customers"], queryFn: fetchCustomers });
  const catalog = useQuery({
    queryKey: ["invoice-catalog"],
    queryFn: fetchCatalog,
    enabled: lineMode === "catalog",
  });
  const recipients = useQuery({
    queryKey: ["invoice-recipients", invoice.customer_id],
    queryFn: () => fetchRecipients(invoice.customer_id),
    enabled: values.recipientSource === "saved",
  });
  const errorRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function change<K extends keyof DraftValues>(name: K, value: DraftValues[K]) {
    setValues((current) => ({ ...current, [name]: value }));
    setDirty(true);
    if (
      name === "recipientSource" ||
      name === "recipientId" ||
      name === "sourceCustomerId" ||
      [
        "party_type",
        "given_name",
        "family_name",
        "organization_name",
        "email",
        "phone",
        "address_line_1",
        "address_line_2",
        "postal_code",
        "city",
        "country_code",
      ].includes(name)
    ) {
      setRecipientDirty(true);
    }
  }

  async function submit(command: Update, after?: () => void) {
    setSaving(true);
    setError("");
    setFields({});
    setConflict(false);
    setSuccess(false);
    try {
      const result = await apiClient.PATCH("/api/v1/invoices/{invoice_id}/", {
        params: { path: { invoice_id: invoice.id } },
        body: { expected_version: invoice.version, ...command },
      });
      if (isInvoice(result.data)) {
        setDirty(false);
        setRecipientDirty(false);
        setSuccess(true);
        after?.();
        onSaved(result.data);
      } else {
        const failure = serverError(result.error);
        setFields(failure.fields);
        if (failure.code === "stale_invoice_version") setConflict(true);
        else
          setError(Object.values(failure.fields).flat()[0]?.message ?? t("invoicePage.saveError"));
        requestAnimationFrame(() => errorRef.current?.focus());
      }
    } catch {
      setError(t("invoicePage.saveError"));
      requestAnimationFrame(() => errorRef.current?.focus());
    } finally {
      setSaving(false);
    }
  }

  function saveDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const command: Update = {
      document_language: values.document_language,
      issue_date: values.issue_date,
      due_date: values.due_date || null,
      ...(recipientDirty ? { recipient: recipientInput(values) } : {}),
      custom_data: customData,
    };
    void submit(command);
  }

  function back() {
    if (dirty && !window.confirm(t("invoicePage.unsaved"))) return;
    onBack();
  }

  const editable = canMutate && invoice.lifecycle_status === "DRAFT";
  const fieldError = (name: string) => fields[name]?.[0]?.message;
  return (
    <>
      <PageHeader title={t("invoicePage.detail")}>
        <button className={buttonClass} onClick={back} type="button">
          {t("invoicePage.back")}
        </button>
      </PageHeader>
      {!editable && <p className="mb-4 text-sm text-neutral-600">{t("invoicePage.readOnly")}</p>}
      {dirty && (
        <p className="mb-4 text-sm text-amber-800" role="status">
          {t("invoicePage.unsaved")}{" "}
          <button
            className={buttonClass}
            onClick={() => {
              setValues(valuesFromInvoice(invoice));
              setCustomData(asCustomData(invoice.custom_data));
              setDirty(false);
              setRecipientDirty(false);
            }}
            type="button"
          >
            {t("invoicePage.discard")}
          </button>
        </p>
      )}
      {success && <p role="status">{t("invoicePage.saved")}</p>}
      {(error || conflict) && (
        <div ref={errorRef} role="alert" tabIndex={-1} className="mb-4 text-red-700">
          <p>{conflict ? t("invoicePage.conflict") : error}</p>
          {conflict && (
            <button
              className={buttonClass}
              onClick={() => {
                setDirty(false);
                onReload();
              }}
              type="button"
            >
              {t("invoicePage.reload")}
            </button>
          )}
        </div>
      )}
      <form className="grid gap-5" onSubmit={saveDraft}>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field
            inputId="invoice-language"
            label={t("invoicePage.language")}
            error={fieldError("document_language")}
          >
            <select
              className={inputClass}
              disabled={!editable}
              id="invoice-language"
              onChange={(e) => change("document_language", e.target.value === "de" ? "de" : "en")}
              value={values.document_language}
            >
              <option value="en">{t("invoicePage.english")}</option>
              <option value="de">{t("invoicePage.german")}</option>
            </select>
          </Field>
          <Field
            inputId="invoice-issue"
            label={t("invoicePage.issueDate")}
            error={fieldError("issue_date")}
          >
            <input
              className={inputClass}
              disabled={!editable}
              id="invoice-issue"
              onChange={(e) => change("issue_date", e.target.value)}
              required
              type="date"
              value={values.issue_date}
            />
          </Field>
          <Field
            inputId="invoice-due"
            label={t("invoicePage.dueDate")}
            error={fieldError("due_date")}
          >
            <input
              className={inputClass}
              disabled={!editable}
              id="invoice-due"
              onChange={(e) => change("due_date", e.target.value)}
              type="date"
              value={values.due_date}
            />
          </Field>
        </div>
        <fieldset className="grid gap-4 rounded-md border border-neutral-200 p-4">
          <legend className="font-medium">{t("invoicePage.recipient")}</legend>
          <Field inputId="invoice-source" label={t("invoicePage.recipient")}>
            <select
              className={inputClass}
              disabled={!editable}
              id="invoice-source"
              onChange={(e) => change("recipientSource", e.target.value as RecipientSource)}
              value={values.recipientSource}
            >
              <option value="customer">{t("invoicePage.recipientCustomer")}</option>
              <option value="saved">{t("invoicePage.recipientSaved")}</option>
              <option value="known_customer">{t("invoicePage.recipientKnown")}</option>
              <option value="manual">{t("invoicePage.recipientManual")}</option>
            </select>
          </Field>
          {values.recipientSource === "saved" && (
            <Field
              inputId="invoice-saved-recipient"
              label={t("invoicePage.savedRecipient")}
              error={fieldError("recipient")}
            >
              <select
                className={inputClass}
                disabled={!editable || recipients.isPending || recipients.isError}
                id="invoice-saved-recipient"
                onChange={(e) => change("recipientId", e.target.value)}
                required
                value={values.recipientId}
              >
                <option value="">{t("invoicePage.selectCustomer")}</option>
                {recipients.data?.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.display_name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {values.recipientSource === "known_customer" && (
            <Field
              inputId="invoice-known-customer"
              label={t("invoicePage.knownCustomer")}
              error={fieldError("recipient")}
            >
              <select
                className={inputClass}
                disabled={!editable || customers.isPending || customers.isError}
                id="invoice-known-customer"
                onChange={(e) => change("sourceCustomerId", e.target.value)}
                required
                value={values.sourceCustomerId}
              >
                <option value="">{t("invoicePage.selectCustomer")}</option>
                {customers.data?.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.display_name}
                  </option>
                ))}
              </select>
            </Field>
          )}
          {values.recipientSource === "manual" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field inputId="recipient-party" label={t("invoicePage.partyType")}>
                <select
                  className={inputClass}
                  disabled={!editable}
                  id="recipient-party"
                  onChange={(e) =>
                    change(
                      "party_type",
                      e.target.value === "organization" ? "organization" : "person",
                    )
                  }
                  value={values.party_type}
                >
                  <option value="person">{t("invoicePage.person")}</option>
                  <option value="organization">{t("invoicePage.organization")}</option>
                </select>
              </Field>
              {(values.party_type === "person"
                ? [
                    ["given_name", "givenName"],
                    ["family_name", "familyName"],
                  ]
                : [["organization_name", "organizationName"]]
              ).map(([name, label]) => (
                <Field
                  key={name}
                  inputId={"recipient-" + name}
                  label={t("invoicePage." + label)}
                  error={fieldError("recipient")}
                >
                  <input
                    className={inputClass}
                    disabled={!editable}
                    id={"recipient-" + name}
                    onChange={(e) => change(name as keyof DraftValues, e.target.value)}
                    required
                    value={values[name as keyof DraftValues]}
                  />
                </Field>
              ))}
              {(
                [
                  ["email", "email"],
                  ["phone", "phone"],
                  ["address_line_1", "addressLine1"],
                  ["address_line_2", "addressLine2"],
                  ["postal_code", "postalCode"],
                  ["city", "city"],
                  ["country_code", "countryCode"],
                ] as const
              ).map(([name, label]) => (
                <Field key={name} inputId={"recipient-" + name} label={t("invoicePage." + label)}>
                  <input
                    className={inputClass}
                    disabled={!editable}
                    id={"recipient-" + name}
                    onChange={(e) => change(name, e.target.value)}
                    required={["address_line_1", "postal_code", "city", "country_code"].includes(
                      name,
                    )}
                    type={name === "email" ? "email" : "text"}
                    value={values[name]}
                  />
                </Field>
              ))}
            </div>
          )}
        </fieldset>
        <CustomFields
          target="invoice"
          values={customData}
          readOnly={!editable}
          showSensitive={canAdminister}
          onChange={(next) => {
            setCustomData(next);
            setDirty(true);
          }}
        />
        {editable && (
          <button className={primaryClass} disabled={saving || !dirty} type="submit">
            {t("invoicePage.save")}
          </button>
        )}
      </form>
      <PresetSection
        invoice={invoice}
        editable={editable}
        dirty={dirty}
        onSaved={onSaved}
        onConflict={() => setConflict(true)}
      />
      <section className="mt-8">
        <h2 className="mb-4 text-xl font-semibold">{t("invoicePage.lines")}</h2>
        {invoice.lines.length === 0 ? (
          <p>{t("invoicePage.noLines")}</p>
        ) : (
          <DataTable caption={t("invoicePage.lines")}>
            <thead>
              <tr>
                <th scope="col">{t("invoicePage.description")}</th>
                <th scope="col">{t("invoicePage.quantity")}</th>
                <th scope="col">{t("invoicePage.unitPrice")}</th>
                <th scope="col">{t("invoicePage.total")}</th>
                {editable && <th scope="col">{t("invoicePage.actions")}</th>}
              </tr>
            </thead>
            <tbody>
              {invoice.lines.map((line, index) => (
                <tr key={line.id}>
                  <td>{line.description}</td>
                  <td>{line.quantity}</td>
                  <td>{line.unit_price}</td>
                  <td>{formatTotal(line.gross_total, invoice.currency)}</td>
                  {editable && (
                    <td className="flex flex-wrap gap-1">
                      <button
                        className={buttonClass}
                        disabled={saving || dirty || index === 0}
                        onClick={() =>
                          void submit({
                            line_operations: [
                              { action: "update", line_id: line.id, position: index },
                            ],
                          })
                        }
                        type="button"
                        aria-label={t("invoicePage.moveUp") + " " + line.description}
                      >
                        {t("invoicePage.moveUp")}
                      </button>
                      <button
                        className={buttonClass}
                        disabled={saving || dirty || index === invoice.lines.length - 1}
                        onClick={() =>
                          void submit({
                            line_operations: [
                              { action: "update", line_id: line.id, position: index + 2 },
                            ],
                          })
                        }
                        type="button"
                        aria-label={t("invoicePage.moveDown") + " " + line.description}
                      >
                        {t("invoicePage.moveDown")}
                      </button>
                      <button
                        className={buttonClass}
                        onClick={() => {
                          setEditingLine(line);
                          setLineMode("edit");
                        }}
                        type="button"
                        aria-label={t("invoicePage.edit") + " " + line.description}
                      >
                        {t("invoicePage.edit")}
                      </button>
                      <button
                        className={buttonClass}
                        disabled={saving || dirty}
                        onClick={() =>
                          void submit({ line_operations: [{ action: "remove", line_id: line.id }] })
                        }
                        type="button"
                        aria-label={t("invoicePage.remove") + " " + line.description}
                      >
                        {t("invoicePage.remove")}
                      </button>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
        {editable && (
          <div className="mt-4 flex gap-2">
            <button className={buttonClass} onClick={() => setLineMode("catalog")} type="button">
              {t("invoicePage.addCatalog")}
            </button>
            <button
              className={buttonClass}
              onClick={() => {
                setEditingLine(null);
                setLineMode("manual");
              }}
              type="button"
            >
              {t("invoicePage.addManual")}
            </button>
          </div>
        )}
        {lineMode === "catalog" && (
          <CatalogLineForm
            showSensitive={canAdminister}
            catalog={catalog.data ?? []}
            loading={catalog.isPending}
            onCancel={() => setLineMode("none")}
            onSave={(operation) =>
              void submit({ line_operations: [operation] }, () => setLineMode("none"))
            }
            saving={saving || dirty}
          />
        )}
        {(lineMode === "manual" || lineMode === "edit") && (
          <ManualLineForm
            showSensitive={canAdminister}
            key={editingLine?.id ?? "new"}
            line={editingLine}
            onCancel={() => setLineMode("none")}
            onSave={(operation) =>
              void submit({ line_operations: [operation] }, () => setLineMode("none"))
            }
            saving={saving || dirty}
          />
        )}
      </section>
      <dl className="mt-8 grid max-w-sm grid-cols-2 gap-2 border-t border-neutral-200 pt-4">
        <dt>{t("invoicePage.subtotal")}</dt>
        <dd>{formatTotal(invoice.subtotal, invoice.currency)}</dd>
        <dt>{t("invoicePage.tax")}</dt>
        <dd>{formatTotal(invoice.tax_total, invoice.currency)}</dd>
        <dt className="font-semibold">{t("invoicePage.total")}</dt>
        <dd className="font-semibold">{formatTotal(invoice.grand_total, invoice.currency)}</dd>
      </dl>
    </>
  );
}

function CatalogLineForm({
  catalog,
  showSensitive,
  loading,
  onSave,
  onCancel,
  saving,
}: {
  catalog: readonly CatalogItem[];
  showSensitive: boolean;
  loading: boolean;
  onSave: (operation: LineOperation) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const { t } = useTranslation("shell");
  const [itemId, setItemId] = useState("");
  const [customData, setCustomData] = useState<Record<string, unknown>>({});
  const [quantity, setQuantity] = useState("1");
  const [discount, setDiscount] = useState("0");
  return (
    <form
      className="mt-4 grid max-w-md gap-3 rounded-md border border-neutral-200 p-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSave({
          action: "add",
          catalog_item_id: Number(itemId),
          custom_data: customData,
          quantity,
          discount_percent: discount,
        });
      }}
    >
      <Field inputId="catalog-line" label={t("invoicePage.catalogItem")}>
        <select
          className={inputClass}
          disabled={loading}
          id="catalog-line"
          onChange={(e) => setItemId(e.target.value)}
          required
          value={itemId}
        >
          <option value="">{t("invoicePage.catalogItem")}</option>
          {catalog
            .filter((item) => !item.is_archived)
            .map((item) => (
              <option key={item.id} value={item.id}>
                {item.code + " — " + item.description_en}
              </option>
            ))}
        </select>
      </Field>
      <Field inputId="catalog-quantity" label={t("invoicePage.quantity")}>
        <input
          className={inputClass}
          id="catalog-quantity"
          min="0.0001"
          onChange={(e) => setQuantity(e.target.value)}
          required
          step="0.0001"
          type="number"
          value={quantity}
        />
      </Field>
      <Field inputId="catalog-discount" label={t("invoicePage.discount")}>
        <input
          className={inputClass}
          id="catalog-discount"
          max="100"
          min="0"
          onChange={(e) => setDiscount(e.target.value)}
          required
          step="0.01"
          type="number"
          value={discount}
        />
      </Field>
      <CustomFields
        target="invoice_line"
        values={customData}
        showSensitive={showSensitive}
        onChange={setCustomData}
      />
      <div className="flex gap-2">
        <button className={primaryClass} disabled={saving} type="submit">
          {t("invoicePage.saveLine")}
        </button>
        <button className={buttonClass} onClick={onCancel} type="button">
          {t("invoicePage.cancel")}
        </button>
      </div>
    </form>
  );
}

function ManualLineForm({
  line,
  onSave,
  onCancel,
  saving,
  showSensitive,
}: {
  line: Line | null;
  showSensitive: boolean;
  onSave: (operation: LineOperation) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const { t } = useTranslation("shell");
  const [description, setDescription] = useState(line?.description ?? "");
  const [customData, setCustomData] = useState<Record<string, unknown>>(
    asCustomData(line?.custom_data),
  );
  const [itemCode, setItemCode] = useState(line?.item_code ?? "");
  const [unit, setUnit] = useState<"C62" | "HUR" | "DAY">(
    line?.unit === "HUR" ? "HUR" : line?.unit === "DAY" ? "DAY" : "C62",
  );
  const [quantity, setQuantity] = useState(line?.quantity ?? "1");
  const [unitPrice, setUnitPrice] = useState(line?.unit_price ?? "");
  const [discount, setDiscount] = useState(line?.discount_percent ?? "0");
  const [taxCategory, setTaxCategory] = useState<"S" | "E">(line?.tax_category === "E" ? "E" : "S");
  const [taxRate, setTaxRate] = useState(line?.tax_rate ?? "19");
  const [priceEntry, setPriceEntry] = useState<"net" | "gross">(
    line?.price_entry_policy === "gross" ? "gross" : "net",
  );
  const [exemptionCode, setExemptionCode] = useState(line?.exemption_reason_code ?? "");
  const [exemptionWording, setExemptionWording] = useState(line?.exemption_wording ?? "");
  function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    onSave({
      action: line ? "update" : "add",
      ...(line ? { line_id: line.id } : {}),
      item_code: itemCode,
      description,
      unit,
      quantity,
      unit_price: unitPrice,
      discount_percent: discount,
      tax_category: taxCategory,
      tax_rate: taxRate,
      price_entry_policy: priceEntry,
      exemption_reason_code: exemptionCode,
      exemption_wording: exemptionWording,
      custom_data: customData,
    });
  }
  return (
    <form
      className="mt-4 grid max-w-2xl gap-3 rounded-md border border-neutral-200 p-4 sm:grid-cols-2"
      onSubmit={save}
    >
      <Field inputId="line-description" label={t("invoicePage.description")}>
        <input
          className={inputClass}
          id="line-description"
          onChange={(e) => setDescription(e.target.value)}
          required
          value={description}
        />
      </Field>
      <Field inputId="line-code" label={t("invoicePage.itemCode")}>
        <input
          className={inputClass}
          id="line-code"
          onChange={(e) => setItemCode(e.target.value)}
          value={itemCode}
        />
      </Field>
      <Field inputId="line-unit" label={t("invoicePage.unit")}>
        <select
          className={inputClass}
          id="line-unit"
          onChange={(e) => setUnit(e.target.value as "C62" | "HUR" | "DAY")}
          value={unit}
        >
          <option value="C62">{t("invoicePage.piece")}</option>
          <option value="HUR">{t("invoicePage.hour")}</option>
          <option value="DAY">{t("invoicePage.day")}</option>
        </select>
      </Field>
      <Field inputId="line-quantity" label={t("invoicePage.quantity")}>
        <input
          className={inputClass}
          id="line-quantity"
          min="0.0001"
          onChange={(e) => setQuantity(e.target.value)}
          required
          step="0.0001"
          type="number"
          value={quantity}
        />
      </Field>
      <Field inputId="line-price" label={t("invoicePage.unitPrice")}>
        <input
          className={inputClass}
          id="line-price"
          min="0"
          onChange={(e) => setUnitPrice(e.target.value)}
          required
          step="0.01"
          type="number"
          value={unitPrice}
        />
      </Field>
      <Field inputId="line-discount" label={t("invoicePage.discount")}>
        <input
          className={inputClass}
          id="line-discount"
          max="100"
          min="0"
          onChange={(e) => setDiscount(e.target.value)}
          required
          step="0.01"
          type="number"
          value={discount}
        />
      </Field>
      <Field inputId="line-tax-category" label={t("invoicePage.taxCategory")}>
        <select
          className={inputClass}
          id="line-tax-category"
          onChange={(e) => setTaxCategory(e.target.value as "S" | "E")}
          value={taxCategory}
        >
          <option value="S">{t("invoicePage.standard")}</option>
          <option value="E">{t("invoicePage.exempt")}</option>
        </select>
      </Field>
      <Field inputId="line-tax-rate" label={t("invoicePage.taxRate")}>
        <input
          className={inputClass}
          id="line-tax-rate"
          max="100"
          min="0"
          onChange={(e) => setTaxRate(e.target.value)}
          required
          step="0.01"
          type="number"
          value={taxRate}
        />
      </Field>
      <Field inputId="line-price-entry" label={t("invoicePage.priceEntry")}>
        <select
          className={inputClass}
          id="line-price-entry"
          onChange={(e) => setPriceEntry(e.target.value as "net" | "gross")}
          value={priceEntry}
        >
          <option value="net">{t("invoicePage.net")}</option>
          <option value="gross">{t("invoicePage.gross")}</option>
        </select>
      </Field>
      {taxCategory === "E" && (
        <>
          <Field inputId="line-exemption-code" label={t("invoicePage.exemptionCode")}>
            <input
              className={inputClass}
              id="line-exemption-code"
              onChange={(e) => setExemptionCode(e.target.value)}
              value={exemptionCode}
            />
          </Field>
          <Field inputId="line-exemption-wording" label={t("invoicePage.exemptionWording")}>
            <input
              className={inputClass}
              id="line-exemption-wording"
              onChange={(e) => setExemptionWording(e.target.value)}
              required
              value={exemptionWording}
            />
          </Field>
        </>
      )}
      <CustomFields
        target="invoice_line"
        values={customData}
        showSensitive={showSensitive}
        onChange={setCustomData}
      />
      <div className="flex gap-2 sm:col-span-2">
        <button className={primaryClass} disabled={saving} type="submit">
          {t("invoicePage.saveLine")}
        </button>
        <button className={buttonClass} onClick={onCancel} type="button">
          {t("invoicePage.cancel")}
        </button>
      </div>
    </form>
  );
}

function presetLine(line: Line): PresetLine {
  return {
    item_code: line.item_code,
    description: line.description,
    unit: line.unit === "HUR" ? "HUR" : line.unit === "DAY" ? "DAY" : "C62",
    quantity: line.quantity,
    unit_price: line.unit_price,
    discount_percent: line.discount_percent,
    tax_category: line.tax_category === "E" ? "E" : "S",
    tax_rate: line.tax_rate,
    price_entry_policy: line.price_entry_policy === "gross" ? "gross" : "net",
    exemption_reason_code: line.exemption_reason_code,
    exemption_wording: line.exemption_wording,
    service_date: line.service_date,
    service_period_end: line.service_period_end,
  };
}

function PresetSection({
  invoice,
  editable,
  dirty,
  onSaved,
  onConflict,
}: {
  invoice: Invoice;
  editable: boolean;
  dirty: boolean;
  onSaved: (invoice: Invoice) => void;
  onConflict: () => void;
}) {
  const { t } = useTranslation("shell");
  const queryClient = useQueryClient();
  const presets = useQuery({
    queryKey: ["invoice-presets"],
    queryFn: async (): Promise<readonly Preset[]> => {
      const { data } = await apiClient.GET("/api/v1/invoice-presets/");
      if (Array.isArray(data)) return data;
      throw new Error("presets_unavailable");
    },
  });
  const [selected, setSelected] = useState("");
  const [mode, setMode] = useState<"append" | "replace">("append");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const selectedId = Number(selected);
  const active = presets.data?.find((preset) => preset.id === selectedId);

  async function run(action: "create" | "update" | "rename" | "archive" | "apply") {
    setBusy(true);
    setError("");
    setSaved(false);
    try {
      if (action === "apply") {
        const result = await apiClient.POST("/api/v1/invoices/{invoice_id}/apply-preset/", {
          params: { path: { invoice_id: invoice.id } },
          body: { preset_id: selectedId, expected_version: invoice.version, mode },
        });
        if (isInvoice(result.data)) {
          onSaved(result.data);
          setSaved(true);
        } else if (serverError(result.error).code === "stale_invoice_version") {
          onConflict();
        } else {
          setError(t("invoicePage.presetError"));
        }
      } else {
        const lines = invoice.lines.map(presetLine);
        const result =
          action === "create"
            ? await apiClient.POST("/api/v1/invoice-presets/", { body: { name, lines } })
            : action === "update"
              ? await apiClient.PATCH("/api/v1/invoice-presets/{preset_id}/", {
                  params: { path: { preset_id: selectedId } },
                  body: { lines },
                })
              : action === "rename"
                ? await apiClient.PATCH("/api/v1/invoice-presets/{preset_id}/", {
                    params: { path: { preset_id: selectedId } },
                    body: { name },
                  })
                : await apiClient.POST("/api/v1/invoice-presets/{preset_id}/archive/", {
                    params: { path: { preset_id: selectedId } },
                  });
        if (result.data) {
          if (action === "create") setSelected(result.data.id.toString());
          if (action === "archive") setSelected("");
          setName("");
          setSaved(true);
          await queryClient.invalidateQueries({ queryKey: ["invoice-presets"] });
        } else {
          setError(t("invoicePage.presetError"));
        }
      }
    } catch {
      setError(t("invoicePage.presetError"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="mt-8 rounded-md border border-neutral-200 p-4"
      aria-label={t("invoicePage.presets")}
    >
      <h2 className="mb-4 text-xl font-semibold">{t("invoicePage.presets")}</h2>
      {presets.isError && <p role="alert">{t("invoicePage.presetError")}</p>}
      {presets.data?.length === 0 && <p>{t("invoicePage.presetsEmpty")}</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field inputId="invoice-preset" label={t("invoicePage.preset")}>
          <select
            className={inputClass}
            id="invoice-preset"
            value={selected}
            onChange={(event) => {
              setSelected(event.target.value);
              setName("");
            }}
          >
            <option value="">{t("invoicePage.selectPreset")}</option>
            {presets.data?.map((preset) => (
              <option key={preset.id} value={preset.id}>
                {preset.name}
              </option>
            ))}
          </select>
        </Field>
        <Field inputId="invoice-preset-mode" label={t("invoicePage.applyMode")}>
          <select
            className={inputClass}
            id="invoice-preset-mode"
            value={mode}
            onChange={(event) => setMode(event.target.value === "replace" ? "replace" : "append")}
            disabled={!editable}
          >
            <option value="append">{t("invoicePage.appendPreset")}</option>
            <option value="replace">{t("invoicePage.replacePreset")}</option>
          </select>
        </Field>
      </div>
      {active && (
        <ol className="my-3 list-decimal ps-5 text-sm">
          {active.lines.map((line, index) => (
            <li key={index}>
              {line.description} — {line.quantity} × {line.unit_price}
            </li>
          ))}
        </ol>
      )}
      {editable && (
        <>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              className={primaryClass}
              type="button"
              disabled={!active || busy || dirty}
              onClick={() => void run("apply")}
            >
              {t("invoicePage.applyPreset")}
            </button>
            <button
              className={buttonClass}
              type="button"
              disabled={!active || busy || dirty || invoice.lines.length === 0}
              onClick={() => void run("update")}
            >
              {t("invoicePage.updatePreset")}
            </button>
            <button
              className={buttonClass}
              type="button"
              disabled={!active || busy}
              onClick={() => void run("archive")}
            >
              {t("invoicePage.archivePreset")}
            </button>
          </div>
          <div className="mt-4 flex max-w-xl flex-wrap items-end gap-2">
            <Field inputId="invoice-preset-name" label={t("invoicePage.presetName")}>
              <input
                className={inputClass}
                id="invoice-preset-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                maxLength={120}
              />
            </Field>
            <button
              className={buttonClass}
              type="button"
              disabled={!name.trim() || !invoice.lines.length || busy || dirty}
              onClick={() => void run("create")}
            >
              {t("invoicePage.savePreset")}
            </button>
            <button
              className={buttonClass}
              type="button"
              disabled={!active || !name.trim() || busy}
              onClick={() => void run("rename")}
            >
              {t("invoicePage.renamePreset")}
            </button>
          </div>
        </>
      )}
      {saved && <p role="status">{t("invoicePage.presetSaved")}</p>}
      {error && <p role="alert">{error}</p>}
    </section>
  );
}
