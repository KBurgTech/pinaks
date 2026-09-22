import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm, useWatch, type FieldPath } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { CustomFields } from "@/custom-fields/custom-fields";
import { DataTable, DestructiveConfirmation, Field, PageHeader, Status } from "@/ui/primitives";

import type { components } from "@/api/generated/schema";

type Customer = components["schemas"]["Customer"];
type CustomerRequest = components["schemas"]["CustomerRequest"];
type Recipient = components["schemas"]["BillingRecipient"];
type RecipientRequest = components["schemas"]["BillingRecipientRequest"];
type ErrorFields = components["schemas"]["ErrorBody"]["fields"];

const inputClass =
  "w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm " +
  "focus-visible:outline-2 focus-visible:outline-offset-2";
const buttonClass =
  "rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm font-medium " +
  "hover:bg-neutral-100 focus-visible:outline-2 focus-visible:outline-offset-2";
const primaryButtonClass =
  "rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white " +
  "hover:bg-neutral-700 focus-visible:outline-2 focus-visible:outline-offset-2";

const EMPTY_CUSTOMER: CustomerRequest = {
  customer_number: "",
  party_type: "person",
  given_name: "",
  family_name: "",
  organization_name: "",
  email: "",
  phone: "",
  preferred_language: "en",
  addresses: [
    {
      label: "primary",
      address_line_1: "",
      address_line_2: "",
      postal_code: "",
      city: "",
      country_code: "DE",
      is_primary: true,
    },
  ],
};

const EMPTY_RECIPIENT: RecipientRequest = {
  party_type: "person",
  given_name: "",
  family_name: "",
  organization_name: "",
  email: "",
  phone: "",
  address_line_1: "",
  address_line_2: "",
  postal_code: "",
  city: "",
  country_code: "DE",
};

class SubmissionError extends Error {
  constructor(readonly fields: ErrorFields) {
    super("customer_submission_failed");
  }
}

function isCustomer(value: unknown): value is Customer {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "number" &&
    "customer_number" in value &&
    typeof value.customer_number === "string" &&
    "party_type" in value &&
    (value.party_type === "person" || value.party_type === "organization") &&
    "given_name" in value &&
    typeof value.given_name === "string" &&
    "family_name" in value &&
    typeof value.family_name === "string" &&
    "organization_name" in value &&
    typeof value.organization_name === "string" &&
    "display_name" in value &&
    typeof value.display_name === "string" &&
    "email" in value &&
    typeof value.email === "string" &&
    "phone" in value &&
    typeof value.phone === "string" &&
    "preferred_language" in value &&
    (value.preferred_language === "en" || value.preferred_language === "de") &&
    "is_archived" in value &&
    typeof value.is_archived === "boolean" &&
    "addresses" in value &&
    Array.isArray(value.addresses)
  );
}

function isRecipient(value: unknown): value is Recipient {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "number" &&
    "display_name" in value &&
    typeof value.display_name === "string" &&
    "customer_id" in value &&
    typeof value.customer_id === "number"
  );
}

function errorFields(value: unknown): ErrorFields {
  if (typeof value !== "object" || value === null || !("error" in value)) {
    return {};
  }
  const error = value.error;
  if (typeof error !== "object" || error === null || !("fields" in error)) {
    return {};
  }
  const fields = error.fields;
  return typeof fields === "object" && fields !== null ? (fields as ErrorFields) : {};
}

function editableCustomer(customer: Customer): CustomerRequest {
  return {
    customer_number: customer.customer_number,
    party_type: customer.party_type,
    given_name: customer.given_name,
    family_name: customer.family_name,
    organization_name: customer.organization_name,
    email: customer.email,
    phone: customer.phone,
    preferred_language: customer.preferred_language,
    addresses: customer.addresses.map((address) => ({
      label: address.label,
      address_line_1: address.address_line_1,
      address_line_2: address.address_line_2,
      postal_code: address.postal_code,
      city: address.city,
      country_code: address.country_code,
      is_primary: address.is_primary,
    })),
  };
}

async function loadCustomers(
  search: string,
  archived: boolean,
): Promise<components["schemas"]["PaginatedCustomerList"]> {
  const { data } = await apiClient.GET("/api/v1/customers/", {
    params: { query: { search, archived, page: 1, page_size: 25 } },
  });
  if (data !== undefined && Array.isArray(data.results) && data.results.every(isCustomer)) {
    return {
      count: data.count,
      next: data.next,
      previous: data.previous,
      results: data.results,
    };
  }
  throw new Error("customers_unavailable");
}

async function saveCustomer(customerId: number | null, values: CustomerRequest): Promise<Customer> {
  const result =
    customerId === null
      ? await apiClient.POST("/api/v1/customers/", { body: values })
      : await apiClient.PATCH("/api/v1/customers/{customer_id}/", {
          params: { path: { customer_id: customerId } },
          body: values,
        });
  if (isCustomer(result.data)) return result.data;
  throw new SubmissionError(errorFields(result.error));
}

interface CustomerFormProps {
  customer?: Customer;
  onCancel: () => void;
  onSaved: (customer: Customer) => void;
}

function CustomerForm({ customer, onCancel, onSaved }: CustomerFormProps) {
  const { t } = useTranslation("shell");
  const [customData, setCustomData] = useState<Record<string, unknown>>(
    customer &&
      typeof customer.custom_data === "object" &&
      customer.custom_data !== null &&
      !Array.isArray(customer.custom_data)
      ? (customer.custom_data as Record<string, unknown>)
      : {},
  );
  const {
    formState: { errors, isDirty },
    handleSubmit,
    register,
    setError,
    control,
  } = useForm<CustomerRequest>({
    defaultValues: customer ? editableCustomer(customer) : EMPTY_CUSTOMER,
  });
  const partyType = useWatch({ control, name: "party_type" });
  const mutation = useMutation({
    mutationFn: (values: CustomerRequest) =>
      saveCustomer(customer?.id ?? null, {
        ...values,
        ...(Object.keys(customData).length ? { custom_data: customData } : {}),
      }),
    onSuccess: onSaved,
    onError(error) {
      if (!(error instanceof SubmissionError)) return;
      for (const [field, messages] of Object.entries(error.fields)) {
        const first = messages[0];
        if (first !== undefined) {
          setError(field as FieldPath<CustomerRequest>, {
            type: first.code,
            message: first.message,
          });
        }
      }
    },
  });

  useEffect(() => {
    if (!isDirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [isDirty]);

  return (
    <form
      className="grid max-w-3xl gap-6"
      onSubmit={(event) => void handleSubmit((values) => mutation.mutate(values))(event)}
    >
      <fieldset className="grid gap-4 md:grid-cols-2">
        <legend className="mb-3 text-lg font-semibold">{t("customer.identity")}</legend>
        <Field
          error={errors.customer_number?.message}
          inputId="customer-number"
          label={t("customer.number")}
        >
          <input
            className={inputClass}
            disabled={customer !== undefined}
            id="customer-number"
            {...register("customer_number")}
          />
        </Field>
        <Field inputId="party-type" label={t("customer.type")}>
          <select className={inputClass} id="party-type" {...register("party_type")}>
            <option value="person">{t("customer.person")}</option>
            <option value="organization">{t("customer.organization")}</option>
          </select>
        </Field>
        {partyType === "person" ? (
          <>
            <Field
              error={errors.given_name?.message}
              inputId="given-name"
              label={t("customer.givenName")}
            >
              <input className={inputClass} id="given-name" {...register("given_name")} />
            </Field>
            <Field
              error={errors.family_name?.message}
              inputId="family-name"
              label={t("customer.familyName")}
            >
              <input className={inputClass} id="family-name" {...register("family_name")} />
            </Field>
          </>
        ) : (
          <Field
            error={errors.organization_name?.message}
            inputId="organization-name"
            label={t("customer.organizationName")}
          >
            <input
              className={inputClass}
              id="organization-name"
              {...register("organization_name")}
            />
          </Field>
        )}
        <Field error={errors.email?.message} inputId="customer-email" label={t("customer.email")}>
          <input className={inputClass} id="customer-email" type="email" {...register("email")} />
        </Field>
        <Field error={errors.phone?.message} inputId="customer-phone" label={t("customer.phone")}>
          <input className={inputClass} id="customer-phone" {...register("phone")} />
        </Field>
        <Field inputId="preferred-language" label={t("customer.preferredLanguage")}>
          <select
            className={inputClass}
            id="preferred-language"
            {...register("preferred_language")}
          >
            <option value="en">{t("customer.english")}</option>
            <option value="de">{t("customer.german")}</option>
          </select>
        </Field>
      </fieldset>
      <fieldset className="grid gap-4 md:grid-cols-2">
        <legend className="mb-3 text-lg font-semibold">{t("customer.primaryAddress")}</legend>
        <Field inputId="address-label" label={t("customer.addressLabel")}>
          <input className={inputClass} id="address-label" {...register("addresses.0.label")} />
        </Field>
        <Field inputId="address-line-1" label={t("customer.addressLine1")}>
          <input
            className={inputClass}
            id="address-line-1"
            {...register("addresses.0.address_line_1")}
          />
        </Field>
        <Field inputId="address-line-2" label={t("customer.addressLine2")}>
          <input
            className={inputClass}
            id="address-line-2"
            {...register("addresses.0.address_line_2")}
          />
        </Field>
        <Field inputId="postal-code" label={t("customer.postalCode")}>
          <input className={inputClass} id="postal-code" {...register("addresses.0.postal_code")} />
        </Field>
        <Field inputId="city" label={t("customer.city")}>
          <input className={inputClass} id="city" {...register("addresses.0.city")} />
        </Field>
        <Field inputId="country-code" label={t("customer.countryCode")}>
          <input
            className={inputClass}
            id="country-code"
            maxLength={2}
            {...register("addresses.0.country_code")}
          />
        </Field>
      </fieldset>
      <CustomFields target="customer" values={customData} onChange={setCustomData} />
      {errors.custom_data?.message && <p role="alert">{errors.custom_data.message}</p>}
      {mutation.isError && !(mutation.error instanceof SubmissionError) && (
        <p role="alert">{t("customer.saveError")}</p>
      )}
      <div className="flex gap-3">
        <button className={primaryButtonClass} disabled={mutation.isPending} type="submit">
          {t(customer ? "customer.save" : "customer.create")}
        </button>
        {isDirty ? (
          <DestructiveConfirmation
            title={t("customer.discardTitle")}
            description={t("customer.discardDescription")}
            triggerLabel={t("customer.cancel")}
            confirmLabel={t("customer.discard")}
            cancelLabel={t("customer.keepEditing")}
            onConfirm={onCancel}
          />
        ) : (
          <button className={buttonClass} onClick={onCancel} type="button">
            {t("customer.cancel")}
          </button>
        )}
      </div>
    </form>
  );
}

interface RecipientFormProps {
  customerId: number;
  recipient?: Recipient;
  onCancel: () => void;
  onSaved: () => void;
}

function RecipientForm({ customerId, recipient, onCancel, onSaved }: RecipientFormProps) {
  const { t } = useTranslation("shell");
  const defaults: RecipientRequest = recipient
    ? {
        party_type: recipient.party_type,
        given_name: recipient.given_name,
        family_name: recipient.family_name,
        organization_name: recipient.organization_name,
        email: recipient.email,
        phone: recipient.phone,
        address_line_1: recipient.address_line_1,
        address_line_2: recipient.address_line_2,
        postal_code: recipient.postal_code,
        city: recipient.city,
        country_code: recipient.country_code,
      }
    : EMPTY_RECIPIENT;
  const { control, handleSubmit, register } = useForm<RecipientRequest>({
    defaultValues: defaults,
  });
  const mutation = useMutation({
    mutationFn: async (body: RecipientRequest) => {
      const result = recipient
        ? await apiClient.PATCH(
            "/api/v1/customers/{customer_id}/billing-recipients/{recipient_id}/",
            {
              params: { path: { customer_id: customerId, recipient_id: recipient.id } },
              body,
            },
          )
        : await apiClient.POST("/api/v1/customers/{customer_id}/billing-recipients/", {
            params: { path: { customer_id: customerId } },
            body,
          });
      if (result.data === undefined) throw new Error("recipient_submission_failed");
      return result.data;
    },
    onSuccess: onSaved,
  });
  const partyType = useWatch({ control, name: "party_type" });

  return (
    <form
      className="grid gap-4 rounded-md border border-neutral-200 p-4 md:grid-cols-2"
      onSubmit={(event) => void handleSubmit((values) => mutation.mutate(values))(event)}
    >
      <Field inputId="recipient-type" label={t("customer.recipientType")}>
        <select className={inputClass} id="recipient-type" {...register("party_type")}>
          <option value="person">{t("customer.person")}</option>
          <option value="organization">{t("customer.organization")}</option>
        </select>
      </Field>
      {partyType === "person" ? (
        <>
          <Field inputId="recipient-given-name" label={t("customer.givenName")}>
            <input className={inputClass} id="recipient-given-name" {...register("given_name")} />
          </Field>
          <Field inputId="recipient-family-name" label={t("customer.familyName")}>
            <input className={inputClass} id="recipient-family-name" {...register("family_name")} />
          </Field>
        </>
      ) : (
        <Field inputId="recipient-organization" label={t("customer.recipientOrganization")}>
          <input
            className={inputClass}
            id="recipient-organization"
            {...register("organization_name")}
          />
        </Field>
      )}
      <Field inputId="recipient-email" label={t("customer.email")}>
        <input className={inputClass} id="recipient-email" type="email" {...register("email")} />
      </Field>
      <Field inputId="recipient-phone" label={t("customer.phone")}>
        <input className={inputClass} id="recipient-phone" {...register("phone")} />
      </Field>
      <Field inputId="recipient-address" label={t("customer.addressLine1")}>
        <input className={inputClass} id="recipient-address" {...register("address_line_1")} />
      </Field>
      <Field inputId="recipient-address-2" label={t("customer.addressLine2")}>
        <input className={inputClass} id="recipient-address-2" {...register("address_line_2")} />
      </Field>
      <Field inputId="recipient-postal" label={t("customer.postalCode")}>
        <input className={inputClass} id="recipient-postal" {...register("postal_code")} />
      </Field>
      <Field inputId="recipient-city" label={t("customer.city")}>
        <input className={inputClass} id="recipient-city" {...register("city")} />
      </Field>
      <Field inputId="recipient-country" label={t("customer.countryCode")}>
        <input className={inputClass} id="recipient-country" {...register("country_code")} />
      </Field>
      {mutation.isError && <p role="alert">{t("customer.recipientSaveError")}</p>}
      <div className="flex gap-3 md:col-span-2">
        <button className={primaryButtonClass} type="submit">
          {t("customer.saveRecipient")}
        </button>
        <button className={buttonClass} onClick={onCancel} type="button">
          {t("customer.cancel")}
        </button>
      </div>
    </form>
  );
}

function CustomerDetail({
  customer,
  canMutate,
  onBack,
  onChanged,
}: {
  customer: Customer;
  canMutate: boolean;
  onBack: () => void;
  onChanged: (customer?: Customer) => void;
}) {
  const { t } = useTranslation("shell");
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [recipientForm, setRecipientForm] = useState<Recipient | "new" | null>(null);
  const recipients = useQuery({
    queryKey: ["billing-recipients", customer.id],
    queryFn: async (): Promise<readonly Recipient[]> => {
      const { data } = await apiClient.GET("/api/v1/customers/{customer_id}/billing-recipients/", {
        params: { path: { customer_id: customer.id } },
      });
      if (Array.isArray(data) && data.every(isRecipient)) return data;
      throw new Error("recipients_unavailable");
    },
    retry: false,
  });
  const archive = useMutation({
    mutationFn: async () => {
      const { response } = await apiClient.DELETE("/api/v1/customers/{customer_id}/", {
        params: { path: { customer_id: customer.id } },
      });
      if (response.status !== 204) throw new Error("archive_failed");
    },
    onSuccess() {
      void queryClient.invalidateQueries({ queryKey: ["customers"] });
      onChanged();
    },
  });

  if (editing) {
    return (
      <CustomerForm
        customer={customer}
        onCancel={() => setEditing(false)}
        onSaved={(saved) => {
          setEditing(false);
          onChanged(saved);
        }}
      />
    );
  }
  const address =
    customer.addresses.find((candidate) => candidate.is_primary) ?? customer.addresses[0];
  return (
    <section>
      <PageHeader title={customer.display_name} description={customer.customer_number}>
        <button className={buttonClass} onClick={onBack} type="button">
          {t("customer.back")}
        </button>
        {canMutate && (
          <button className={buttonClass} onClick={() => setEditing(true)} type="button">
            {t("customer.edit")}
          </button>
        )}
        {canMutate && !customer.is_archived && (
          <DestructiveConfirmation
            title={t("customer.archiveTitle", { name: customer.display_name })}
            description={t("customer.archiveDescription")}
            triggerLabel={t("customer.archiveCustomer")}
            confirmLabel={t("customer.archive")}
            cancelLabel={t("customer.cancel")}
            onConfirm={() => archive.mutate()}
          />
        )}
      </PageHeader>
      {!canMutate && (
        <p className="mb-4 rounded-md bg-blue-50 p-3 text-sm text-blue-900">
          {t("customer.readOnlyDescription")}
        </p>
      )}
      <dl className="grid gap-4 sm:grid-cols-2">
        <div>
          <dt className="text-sm font-medium text-neutral-600">{t("customer.email")}</dt>
          <dd>{customer.email || "—"}</dd>
        </div>
        <div>
          <dt className="text-sm font-medium text-neutral-600">{t("customer.phone")}</dt>
          <dd>{customer.phone || "—"}</dd>
        </div>
        <div>
          <dt className="text-sm font-medium text-neutral-600">
            {t("customer.preferredLanguage")}
          </dt>
          <dd>
            {t(customer.preferred_language === "de" ? "customer.german" : "customer.english")}
          </dd>
        </div>
        <div>
          <dt className="text-sm font-medium text-neutral-600">{t("customer.status")}</dt>
          <dd>
            <Status tone={customer.is_archived ? "neutral" : "success"}>
              {t(customer.is_archived ? "customer.archived" : "customer.active")}
            </Status>
          </dd>
        </div>
        {address && (
          <div>
            <dt className="text-sm font-medium text-neutral-600">{t("customer.primaryAddress")}</dt>
            <dd>
              {address.address_line_1}
              <br />
              {address.postal_code} {address.city}
              <br />
              {address.country_code}
            </dd>
          </div>
        )}
      </dl>
      <section className="mt-8">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold">{t("customer.recipients")}</h2>
          {canMutate && recipientForm === null && (
            <button className={buttonClass} onClick={() => setRecipientForm("new")} type="button">
              {t("customer.addRecipient")}
            </button>
          )}
        </div>
        {recipientForm !== null && (
          <RecipientForm
            customerId={customer.id}
            recipient={recipientForm === "new" ? undefined : recipientForm}
            onCancel={() => setRecipientForm(null)}
            onSaved={() => {
              setRecipientForm(null);
              void recipients.refetch();
            }}
          />
        )}
        {recipients.isError && <p role="alert">{t("customer.recipientLoadError")}</p>}
        {recipients.data?.length === 0 && recipientForm === null && (
          <p>{t("customer.noRecipients")}</p>
        )}
        {recipients.data?.map((recipient) => (
          <div
            className="mt-3 flex items-center justify-between rounded-md border border-neutral-200 p-3"
            key={recipient.id}
          >
            <span>{recipient.display_name}</span>
            {canMutate && (
              <button
                className={buttonClass}
                onClick={() => setRecipientForm(recipient)}
                type="button"
              >
                {t("customer.editRecipient", { name: recipient.display_name })}
              </button>
            )}
          </div>
        ))}
      </section>
    </section>
  );
}

export function CustomerPage({ canMutate }: { canMutate: boolean }) {
  const { t } = useTranslation("shell");
  const queryClient = useQueryClient();
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState(false);
  const [selection, setSelection] = useState<Customer | "new" | null>(null);
  const customers = useQuery({
    queryKey: ["customers", search, archived],
    queryFn: () => loadCustomers(search, archived),
    retry: false,
  });

  if (selection === "new") {
    return (
      <CustomerForm
        onCancel={() => setSelection(null)}
        onSaved={(saved) => {
          void queryClient.invalidateQueries({ queryKey: ["customers"] });
          setSelection(saved);
        }}
      />
    );
  }
  if (selection !== null) {
    return (
      <CustomerDetail
        customer={selection}
        canMutate={canMutate}
        onBack={() => setSelection(null)}
        onChanged={(changed) => setSelection(changed ?? null)}
      />
    );
  }
  return (
    <section>
      <PageHeader title={t("customer.heading")} description={t("customer.description")}>
        {canMutate ? (
          <button className={primaryButtonClass} onClick={() => setSelection("new")} type="button">
            {t("customer.new")}
          </button>
        ) : (
          <Status tone="info">{t("customer.readOnly")}</Status>
        )}
      </PageHeader>
      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          setSearch(searchInput);
        }}
      >
        <Field inputId="customer-search" label={t("customer.search")}>
          <input
            className={inputClass}
            id="customer-search"
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </Field>
        <button className={buttonClass} type="submit">
          {t("customer.searchAction")}
        </button>
        <label className="flex items-center gap-2 py-2 text-sm">
          <input
            checked={archived}
            onChange={(event) => setArchived(event.target.checked)}
            type="checkbox"
          />
          {t("customer.showArchived")}
        </label>
      </form>
      {customers.isPending && <p>{t("customer.loading")}</p>}
      {customers.isError && <p role="alert">{t("customer.loadError")}</p>}
      {customers.data?.results.length === 0 && <p>{t("customer.empty")}</p>}
      {customers.data && customers.data.results.length > 0 && (
        <DataTable caption={t("customer.tableCaption")}>
          <thead>
            <tr className="border-b border-neutral-200 text-left">
              <th className="p-3">{t("customer.number")}</th>
              <th className="p-3">{t("customer.name")}</th>
              <th className="p-3">{t("customer.email")}</th>
              <th className="p-3">{t("customer.preferredLanguage")}</th>
              <th className="p-3">{t("customer.status")}</th>
              <th className="p-3">{t("customer.actions")}</th>
            </tr>
          </thead>
          <tbody>
            {customers.data.results.map((customer) => (
              <tr className="border-b border-neutral-100" key={customer.id}>
                <td className="p-3">{customer.customer_number}</td>
                <td className="p-3">{customer.display_name}</td>
                <td className="p-3">{customer.email || "—"}</td>
                <td className="p-3">
                  {t(customer.preferred_language === "de" ? "customer.german" : "customer.english")}
                </td>
                <td className="p-3">
                  <Status tone={customer.is_archived ? "neutral" : "success"}>
                    {t(customer.is_archived ? "customer.archived" : "customer.active")}
                  </Status>
                </td>
                <td className="p-3">
                  <button
                    className={buttonClass}
                    onClick={() => setSelection(customer)}
                    type="button"
                    aria-label={t("customer.view", { name: customer.display_name })}
                  >
                    {t("customer.open")}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </section>
  );
}
