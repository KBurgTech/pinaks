import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm, type FieldPath } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { isTaxProfile } from "@/catalog/validators";
import { DataTable, DestructiveConfirmation, Field, PageHeader, Status } from "@/ui/primitives";

import type { components } from "@/api/generated/schema";

type CatalogItem = components["schemas"]["CatalogItem"];
type CatalogItemRequest = components["schemas"]["CatalogItemRequest"];
type ErrorFields = components["schemas"]["ErrorBody"]["fields"];
type TaxProfile = components["schemas"]["TaxProfile"];

const inputClass =
  "w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 disabled:bg-neutral-100";
const buttonClass =
  "rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm font-medium " +
  "hover:bg-neutral-100 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50";
const primaryButtonClass =
  "rounded-md bg-neutral-900 px-3 py-2 text-sm font-medium text-white " +
  "hover:bg-neutral-700 focus-visible:outline-2 focus-visible:outline-offset-2";

const EMPTY_ITEM: CatalogItemRequest = {
  code: "",
  description_en: "",
  description_de: "",
  unit: "C62",
  default_price: "",
  minimum_price: "",
  maximum_price: "",
  default_tax_profile_id: 0,
};

class SubmissionError extends Error {
  constructor(readonly fields: ErrorFields) {
    super("catalog_submission_failed");
  }
}

function isCatalogItem(value: unknown): value is CatalogItem {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "number" &&
    "code" in value &&
    typeof value.code === "string" &&
    "description_en" in value &&
    typeof value.description_en === "string" &&
    "description_de" in value &&
    typeof value.description_de === "string" &&
    "default_price" in value &&
    typeof value.default_price === "string"
  );
}

function errorFields(value: unknown): ErrorFields {
  if (typeof value !== "object" || value === null || !("error" in value)) return {};
  const error = value.error;
  if (typeof error !== "object" || error === null || !("fields" in error)) return {};
  return typeof error.fields === "object" && error.fields !== null
    ? (error.fields as ErrorFields)
    : {};
}

function editableItem(item: CatalogItem): CatalogItemRequest {
  return {
    code: item.code,
    description_en: item.description_en,
    description_de: item.description_de,
    unit: item.unit,
    default_price: item.default_price,
    minimum_price: item.minimum_price ?? "",
    maximum_price: item.maximum_price ?? "",
    default_tax_profile_id: item.default_tax_profile.id,
  };
}

function formatEuro(value: string, language: string): string {
  const [rawInteger, fraction] = value.split(".");
  const negative = rawInteger.startsWith("-");
  const digits = negative ? rawInteger.slice(1) : rawInteger;
  const separator = language === "de" ? "." : ",";
  const decimalSeparator = language === "de" ? "," : ".";
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, separator);
  const amount = `${negative ? "-" : ""}${grouped}${fraction ? decimalSeparator + fraction : ""}`;
  return language === "de" ? `${amount}\u00a0€` : `€${amount}`;
}

async function loadCatalog(
  search: string,
  archived: boolean,
  page: number,
): Promise<components["schemas"]["PaginatedCatalogItemList"]> {
  const { data } = await apiClient.GET("/api/v1/catalog/", {
    params: { query: { search, archived, page, page_size: 25 } },
  });
  if (data !== undefined && Array.isArray(data.results) && data.results.every(isCatalogItem)) {
    return {
      count: data.count,
      next: data.next,
      previous: data.previous,
      results: data.results,
    };
  }
  throw new Error("catalog_unavailable");
}

async function loadTaxProfiles(): Promise<readonly TaxProfile[]> {
  const { data } = await apiClient.GET("/api/v1/configuration/tax-profiles/");
  if (Array.isArray(data) && data.every(isTaxProfile)) {
    return data.filter((profile) => profile.is_current);
  }
  throw new Error("tax_profiles_unavailable");
}

async function saveItem(itemId: number | null, values: CatalogItemRequest): Promise<CatalogItem> {
  const body: CatalogItemRequest = {
    ...values,
    minimum_price: values.minimum_price === "" ? null : values.minimum_price,
    maximum_price: values.maximum_price === "" ? null : values.maximum_price,
  };
  const result =
    itemId === null
      ? await apiClient.POST("/api/v1/catalog/", { body })
      : await apiClient.PATCH("/api/v1/catalog/{item_id}/", {
          params: { path: { item_id: itemId } },
          body,
        });
  if (isCatalogItem(result.data)) return result.data;
  throw new SubmissionError(errorFields(result.error));
}

function CatalogForm({
  item,
  taxProfiles,
  onCancel,
  onSaved,
}: {
  item?: CatalogItem;
  taxProfiles: readonly TaxProfile[];
  onCancel: () => void;
  onSaved: (item: CatalogItem) => void;
}) {
  const { t } = useTranslation("shell");
  const {
    formState: { errors },
    handleSubmit,
    register,
    setError,
    setValue,
  } = useForm<CatalogItemRequest>({ defaultValues: item ? editableItem(item) : EMPTY_ITEM });
  const mutation = useMutation({
    mutationFn: (values: CatalogItemRequest) => saveItem(item?.id ?? null, values),
    onSuccess: onSaved,
    onError(error) {
      if (!(error instanceof SubmissionError)) return;
      for (const [field, messages] of Object.entries(error.fields)) {
        const first = messages[0];
        if (first !== undefined) {
          setError(field as FieldPath<CatalogItemRequest>, {
            type: first.code,
            message: first.message,
          });
        }
      }
    },
  });

  useEffect(() => {
    if (item === undefined && taxProfiles.length > 0) {
      setValue("default_tax_profile_id", taxProfiles[0]?.id ?? 0);
    }
  }, [item, setValue, taxProfiles]);

  return (
    <form
      className="grid max-w-3xl gap-6"
      onSubmit={(event) => void handleSubmit((values) => mutation.mutate(values))(event)}
    >
      <PageHeader
        title={t(item ? "catalogPage.editHeading" : "catalogPage.newHeading")}
        description={t("catalogPage.formDescription")}
      />
      <fieldset className="grid gap-4 md:grid-cols-2">
        <legend className="mb-3 text-lg font-semibold">{t("catalogPage.identity")}</legend>
        <Field error={errors.code?.message} inputId="catalog-code" label={t("catalogPage.code")}>
          <input
            autoFocus={item === undefined}
            className={inputClass}
            disabled={item !== undefined}
            id="catalog-code"
            {...register("code")}
          />
        </Field>
        <Field inputId="catalog-unit" label={t("catalogPage.unit")}>
          <select className={inputClass} id="catalog-unit" {...register("unit")}>
            <option value="C62">{t("catalogPage.unitPiece")}</option>
            <option value="HUR">{t("catalogPage.unitHour")}</option>
            <option value="DAY">{t("catalogPage.unitDay")}</option>
          </select>
        </Field>
        <Field
          error={errors.description_en?.message}
          inputId="description-en"
          label={t("catalogPage.descriptionEn")}
        >
          <input className={inputClass} id="description-en" {...register("description_en")} />
        </Field>
        <Field
          error={errors.description_de?.message}
          inputId="description-de"
          label={t("catalogPage.descriptionDe")}
        >
          <input className={inputClass} id="description-de" {...register("description_de")} />
        </Field>
      </fieldset>
      <fieldset className="grid gap-4 md:grid-cols-2">
        <legend className="mb-3 text-lg font-semibold">{t("catalogPage.pricing")}</legend>
        <Field
          error={errors.default_price?.message}
          inputId="default-price"
          label={t("catalogPage.defaultPrice")}
        >
          <input
            className={inputClass}
            id="default-price"
            inputMode="decimal"
            {...register("default_price")}
          />
        </Field>
        <Field
          error={errors.minimum_price?.message}
          inputId="minimum-price"
          label={t("catalogPage.minimumPrice")}
        >
          <input
            className={inputClass}
            id="minimum-price"
            inputMode="decimal"
            {...register("minimum_price")}
          />
        </Field>
        <Field
          error={errors.maximum_price?.message}
          inputId="maximum-price"
          label={t("catalogPage.maximumPrice")}
        >
          <input
            className={inputClass}
            id="maximum-price"
            inputMode="decimal"
            {...register("maximum_price")}
          />
        </Field>
        <Field
          error={errors.default_tax_profile_id?.message}
          inputId="default-tax-profile"
          label={t("catalogPage.defaultTaxProfile")}
        >
          <select
            className={inputClass}
            id="default-tax-profile"
            {...register("default_tax_profile_id", { valueAsNumber: true })}
          >
            {taxProfiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.name} ({profile.rate}%)
              </option>
            ))}
          </select>
        </Field>
      </fieldset>
      {mutation.isError && !(mutation.error instanceof SubmissionError) && (
        <p role="alert">{t("catalogPage.saveError")}</p>
      )}
      <div className="flex gap-3">
        <button className={primaryButtonClass} type="submit">
          {t(item ? "catalogPage.save" : "catalogPage.create")}
        </button>
        <button className={buttonClass} onClick={onCancel} type="button">
          {t("catalogPage.cancel")}
        </button>
      </div>
    </form>
  );
}

function CatalogDetail({
  item,
  canMutate,
  onBack,
  onChanged,
}: {
  item: CatalogItem;
  canMutate: boolean;
  onBack: () => void;
  onChanged: (item?: CatalogItem) => void;
}) {
  const { i18n, t } = useTranslation("shell");
  const queryClient = useQueryClient();
  const [editing, setEditing] = useState(false);
  const taxProfiles = useQuery({
    queryKey: ["tax-profiles"],
    queryFn: loadTaxProfiles,
    retry: false,
  });
  const archive = useMutation({
    mutationFn: async () => {
      const { response } = await apiClient.DELETE("/api/v1/catalog/{item_id}/", {
        params: { path: { item_id: item.id } },
      });
      if (response.status !== 204) throw new Error("archive_failed");
    },
    onSuccess() {
      void queryClient.invalidateQueries({ queryKey: ["catalog"] });
      onChanged();
    },
  });

  if (editing && taxProfiles.data !== undefined) {
    return (
      <CatalogForm
        item={item}
        taxProfiles={taxProfiles.data}
        onCancel={() => setEditing(false)}
        onSaved={(saved) => {
          setEditing(false);
          onChanged(saved);
        }}
      />
    );
  }

  const language = i18n.resolvedLanguage === "de" ? "de" : "en";
  return (
    <section>
      <PageHeader
        title={item.code}
        description={language === "de" ? item.description_de : item.description_en}
      >
        <button className={buttonClass} onClick={onBack} type="button">
          {t("catalogPage.back")}
        </button>
        {canMutate && (
          <button className={buttonClass} onClick={() => setEditing(true)} type="button">
            {t("catalogPage.edit")}
          </button>
        )}
        {canMutate && !item.is_archived && (
          <DestructiveConfirmation
            title={t("catalogPage.archiveTitle", { code: item.code })}
            description={t("catalogPage.archiveDescription")}
            triggerLabel={t("catalogPage.archiveItem")}
            confirmLabel={t("catalogPage.archive")}
            cancelLabel={t("catalogPage.cancel")}
            onConfirm={() => archive.mutate()}
          />
        )}
      </PageHeader>
      {!canMutate && (
        <p className="mb-4 rounded-md bg-blue-50 p-3 text-sm text-blue-900">
          {t("catalogPage.readOnlyDescription")}
        </p>
      )}
      <dl className="grid gap-4 sm:grid-cols-2">
        <div>
          <dt className="text-sm font-medium text-neutral-600">{t("catalogPage.descriptionEn")}</dt>
          <dd>{item.description_en}</dd>
        </div>
        <div>
          <dt className="text-sm font-medium text-neutral-600">{t("catalogPage.descriptionDe")}</dt>
          <dd>{item.description_de}</dd>
        </div>
        <div>
          <dt className="text-sm font-medium text-neutral-600">{t("catalogPage.unit")}</dt>
          <dd>{t(`catalogPage.units.${item.unit}`)}</dd>
        </div>
        <div>
          <dt className="text-sm font-medium text-neutral-600">{t("catalogPage.defaultPrice")}</dt>
          <dd>{formatEuro(item.default_price, language)}</dd>
        </div>
        <div>
          <dt className="text-sm font-medium text-neutral-600">{t("catalogPage.priceRange")}</dt>
          <dd>
            {item.minimum_price ? formatEuro(item.minimum_price, language) : "—"} –{" "}
            {item.maximum_price ? formatEuro(item.maximum_price, language) : "—"}
          </dd>
        </div>
        <div>
          <dt className="text-sm font-medium text-neutral-600">
            {t("catalogPage.defaultTaxProfile")}
          </dt>
          <dd>
            {item.default_tax_profile.name} ({item.default_tax_profile.rate}%)
          </dd>
        </div>
        <div>
          <dt className="text-sm font-medium text-neutral-600">
            {t("catalogPage.translationStatus")}
          </dt>
          <dd>
            <Status tone="success">{t("catalogPage.translationsComplete")}</Status>
          </dd>
        </div>
        <div>
          <dt className="text-sm font-medium text-neutral-600">{t("catalogPage.status")}</dt>
          <dd>
            <Status tone={item.is_archived ? "neutral" : "success"}>
              {t(item.is_archived ? "catalogPage.archived" : "catalogPage.active")}
            </Status>
          </dd>
        </div>
      </dl>
    </section>
  );
}

export function CatalogPage({ canMutate }: { canMutate: boolean }) {
  const { i18n, t } = useTranslation("shell");
  const queryClient = useQueryClient();
  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState(false);
  const [page, setPage] = useState(1);
  const [selection, setSelection] = useState<CatalogItem | "new" | null>(null);
  const catalog = useQuery({
    queryKey: ["catalog", search, archived, page],
    queryFn: () => loadCatalog(search, archived, page),
    retry: false,
  });
  const taxProfiles = useQuery({
    queryKey: ["tax-profiles"],
    queryFn: loadTaxProfiles,
    retry: false,
  });

  if (selection === "new") {
    return (
      <CatalogForm
        taxProfiles={taxProfiles.data ?? []}
        onCancel={() => setSelection(null)}
        onSaved={(saved) => {
          void queryClient.invalidateQueries({ queryKey: ["catalog"] });
          setSelection(saved);
        }}
      />
    );
  }
  if (selection !== null) {
    return (
      <CatalogDetail
        item={selection}
        canMutate={canMutate}
        onBack={() => setSelection(null)}
        onChanged={(changed) => setSelection(changed ?? null)}
      />
    );
  }

  const language = i18n.resolvedLanguage === "de" ? "de" : "en";
  return (
    <section>
      <PageHeader title={t("catalogPage.heading")} description={t("catalogPage.description")}>
        {canMutate ? (
          <button className={primaryButtonClass} onClick={() => setSelection("new")} type="button">
            {t("catalogPage.new")}
          </button>
        ) : (
          <Status tone="info">{t("catalogPage.readOnly")}</Status>
        )}
      </PageHeader>
      <form
        className="mb-4 flex flex-wrap items-end gap-3"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          setPage(1);
          setSearch(searchInput);
        }}
      >
        <Field inputId="catalog-search" label={t("catalogPage.search")}>
          <input
            className={inputClass}
            id="catalog-search"
            type="search"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </Field>
        <button className={buttonClass} type="submit">
          {t("catalogPage.searchAction")}
        </button>
        <label className="flex items-center gap-2 py-2 text-sm">
          <input
            checked={archived}
            onChange={(event) => {
              setArchived(event.target.checked);
              setPage(1);
            }}
            type="checkbox"
          />
          {t("catalogPage.showArchived")}
        </label>
      </form>
      {catalog.isPending && <p>{t("catalogPage.loading")}</p>}
      {catalog.isError && <p role="alert">{t("catalogPage.loadError")}</p>}
      {catalog.data?.results.length === 0 && <p>{t("catalogPage.empty")}</p>}
      {catalog.data && catalog.data.results.length > 0 && (
        <>
          <DataTable caption={t("catalogPage.tableCaption")}>
            <thead>
              <tr className="border-b border-neutral-200 text-left">
                <th className="p-3">{t("catalogPage.code")}</th>
                <th className="p-3">{t("catalogPage.descriptionEn")}</th>
                <th className="p-3">{t("catalogPage.descriptionDe")}</th>
                <th className="p-3">{t("catalogPage.defaultPrice")}</th>
                <th className="p-3">{t("catalogPage.translationStatus")}</th>
                <th className="p-3">{t("catalogPage.actions")}</th>
              </tr>
            </thead>
            <tbody>
              {catalog.data.results.map((item) => (
                <tr className="border-b border-neutral-100" key={item.id}>
                  <td className="p-3">{item.code}</td>
                  <td className="p-3">{item.description_en}</td>
                  <td className="p-3">{item.description_de}</td>
                  <td className="p-3">{formatEuro(item.default_price, language)}</td>
                  <td className="p-3">
                    <Status tone="success">{t("catalogPage.translationsComplete")}</Status>
                  </td>
                  <td className="p-3">
                    <button
                      aria-label={t("catalogPage.view", { code: item.code })}
                      className={buttonClass}
                      onClick={() => setSelection(item)}
                      type="button"
                    >
                      {t("catalogPage.open")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
          <nav aria-label={t("catalogPage.pagination")} className="mt-4 flex justify-end gap-3">
            <button
              aria-label={t("catalogPage.previousPage")}
              className={buttonClass}
              disabled={!catalog.data.previous}
              onClick={() => setPage((value) => Math.max(1, value - 1))}
              type="button"
            >
              {t("catalogPage.previous")}
            </button>
            <button
              aria-label={t("catalogPage.nextPage")}
              className={buttonClass}
              disabled={!catalog.data.next}
              onClick={() => setPage((value) => value + 1)}
              type="button"
            >
              {t("catalogPage.next")}
            </button>
          </nav>
        </>
      )}
    </section>
  );
}
