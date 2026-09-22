import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { Field, PageHeader } from "@/ui/primitives";

import type { components } from "@/api/generated/schema";

type TaxProfile = components["schemas"]["TaxProfile"];
type TaxProfileInput = components["schemas"]["TaxProfileRequest"];

const EMPTY_PROFILE: TaxProfileInput = {
  code: "",
  name: "",
  tax_category: "S",
  rate: "19.00",
  exemption_reason_code: "",
  exemption_wording_en: "",
  exemption_wording_de: "",
  price_entry_policy: "net",
  tax_column_policy: "show",
  required_seller_identifiers: ["tax_number"],
  is_default: true,
};

const inputClass =
  "w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm " +
  "focus-visible:outline-2 focus-visible:outline-offset-2";

function isTaxProfile(value: unknown): value is TaxProfile {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "number" &&
    "code" in value &&
    typeof value.code === "string" &&
    "version" in value &&
    typeof value.version === "number" &&
    "name" in value &&
    typeof value.name === "string" &&
    "tax_category" in value &&
    (value.tax_category === "S" || value.tax_category === "E") &&
    "rate" in value &&
    typeof value.rate === "string" &&
    "exemption_reason_code" in value &&
    typeof value.exemption_reason_code === "string" &&
    "exemption_wording_en" in value &&
    typeof value.exemption_wording_en === "string" &&
    "exemption_wording_de" in value &&
    typeof value.exemption_wording_de === "string" &&
    "price_entry_policy" in value &&
    (value.price_entry_policy === "net" || value.price_entry_policy === "gross") &&
    "tax_column_policy" in value &&
    (value.tax_column_policy === "show" || value.tax_column_policy === "hide") &&
    "required_seller_identifiers" in value &&
    Array.isArray(value.required_seller_identifiers) &&
    "is_default" in value &&
    typeof value.is_default === "boolean" &&
    "is_current" in value &&
    typeof value.is_current === "boolean" &&
    "translation_complete" in value &&
    typeof value.translation_complete === "boolean"
  );
}
async function loadTaxProfiles(): Promise<readonly TaxProfile[]> {
  const { data } = await apiClient.GET("/api/v1/configuration/tax-profiles/");
  if (Array.isArray(data) && data.every(isTaxProfile)) {
    return data;
  }
  throw new Error("tax_profiles_unavailable");
}

async function createTaxProfile(profile: TaxProfileInput) {
  const { data } = await apiClient.POST("/api/v1/configuration/tax-profiles/", {
    body: profile,
  });
  if (data !== undefined) {
    return data;
  }
  throw new Error("tax_profile_submission_failed");
}

export function TaxProfileForm() {
  const { t } = useTranslation("shell");
  const queryClient = useQueryClient();
  const [saved, setSaved] = useState(false);
  const profiles = useQuery({
    queryKey: ["tax-profiles"],
    queryFn: loadTaxProfiles,
    retry: false,
  });
  const { control, handleSubmit, register, reset, setValue } = useForm<TaxProfileInput>({
    defaultValues: EMPTY_PROFILE,
  });
  const [category, wordingEn, wordingDe] = useWatch({
    control,
    name: ["tax_category", "exemption_wording_en", "exemption_wording_de"],
  });
  const translationsComplete =
    category !== "E" || (wordingEn.trim().length > 0 && wordingDe.trim().length > 0);
  const mutation = useMutation({
    mutationFn: createTaxProfile,
    onSuccess() {
      setSaved(true);
      reset(EMPTY_PROFILE);
      void queryClient.invalidateQueries({ queryKey: ["tax-profiles"] });
    },
    onError() {
      setSaved(false);
    },
  });

  return (
    <section className="mt-12 border-t border-neutral-300 pt-8">
      <PageHeader title={t("taxProfiles.heading")} description={t("taxProfiles.description")} />

      {profiles.isError && <p role="alert">{t("taxProfiles.loadError")}</p>}
      {profiles.data !== undefined && profiles.data.length > 0 && (
        <ul className="mb-6 grid gap-2" aria-label={t("taxProfiles.existingProfiles")}>
          {profiles.data.map((profile) => (
            <li className="rounded-md border border-neutral-200 bg-white p-3" key={profile.id}>
              {profile.name} · {profile.rate}% · v{profile.version}
              {profile.is_default ? ` · ${t("taxProfiles.defaultProfile")}` : ""}
            </li>
          ))}
        </ul>
      )}

      <form
        className="grid max-w-3xl gap-6"
        onSubmit={(event) => void handleSubmit((values) => mutation.mutate(values))(event)}
      >
        <div className="grid gap-4 md:grid-cols-2">
          <Field inputId="tax-profile-code" label={t("taxProfiles.code")}>
            <input className={inputClass} id="tax-profile-code" {...register("code")} />
          </Field>
          <Field inputId="tax-profile-name" label={t("taxProfiles.name")}>
            <input className={inputClass} id="tax-profile-name" {...register("name")} />
          </Field>
          <Field inputId="tax-category" label={t("taxProfiles.category")}>
            <select
              className={inputClass}
              id="tax-category"
              {...register("tax_category", {
                onChange(event: React.ChangeEvent<HTMLSelectElement>) {
                  if (event.target.value === "E") {
                    setValue("rate", "0.00");
                    setValue("tax_column_policy", "hide");
                  }
                },
              })}
            >
              <option value="S">{t("taxProfiles.standard")}</option>
              <option value="E">{t("taxProfiles.exempt")}</option>
            </select>
          </Field>
          <Field inputId="tax-rate" label={t("taxProfiles.rate")}>
            <input className={inputClass} id="tax-rate" inputMode="decimal" {...register("rate")} />
          </Field>
          <Field inputId="price-entry-policy" label={t("taxProfiles.priceEntryPolicy")}>
            <select
              className={inputClass}
              id="price-entry-policy"
              {...register("price_entry_policy")}
            >
              <option value="net">{t("taxProfiles.net")}</option>
              <option value="gross">{t("taxProfiles.gross")}</option>
            </select>
          </Field>
          <Field inputId="tax-column-policy" label={t("taxProfiles.taxColumnPolicy")}>
            <select
              className={inputClass}
              id="tax-column-policy"
              {...register("tax_column_policy")}
            >
              <option value="show">{t("taxProfiles.show")}</option>
              <option value="hide">{t("taxProfiles.hide")}</option>
            </select>
          </Field>
        </div>

        {category === "E" && (
          <fieldset className="grid gap-4 md:grid-cols-2">
            <legend className="mb-2 font-semibold">{t("taxProfiles.exemption")}</legend>
            <Field inputId="exemption-code" label={t("taxProfiles.exemptionCode")}>
              <input
                className={inputClass}
                id="exemption-code"
                {...register("exemption_reason_code")}
              />
            </Field>
            <div />
            <Field inputId="wording-en" label={t("taxProfiles.wordingEn")}>
              <textarea
                className={inputClass}
                id="wording-en"
                {...register("exemption_wording_en")}
              />
            </Field>
            <Field inputId="wording-de" label={t("taxProfiles.wordingDe")}>
              <textarea
                className={inputClass}
                id="wording-de"
                {...register("exemption_wording_de")}
              />
            </Field>
            <p
              aria-label={t("taxProfiles.translationStatus")}
              className="md:col-span-2"
              role="status"
            >
              {t(
                translationsComplete
                  ? "taxProfiles.translationsComplete"
                  : "taxProfiles.translationsIncomplete",
              )}
            </p>
          </fieldset>
        )}

        <fieldset className="grid gap-2">
          <legend className="font-semibold">{t("taxProfiles.sellerIdentifiers")}</legend>
          <label>
            <input
              type="checkbox"
              value="tax_number"
              {...register("required_seller_identifiers")}
            />{" "}
            {t("taxProfiles.taxNumber")}
          </label>
          <label>
            <input
              type="checkbox"
              value="vat_identifier"
              {...register("required_seller_identifiers")}
            />{" "}
            {t("taxProfiles.vatIdentifier")}
          </label>
          <label>
            <input type="checkbox" {...register("is_default")} /> {t("taxProfiles.makeDefault")}
          </label>
        </fieldset>

        <div className="flex items-center gap-4">
          <button
            className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white"
            disabled={mutation.isPending || !translationsComplete}
            type="submit"
          >
            {t("taxProfiles.save")}
          </button>
          {saved && <p role="status">{t("taxProfiles.saved")}</p>}
          {mutation.isError && <p role="alert">{t("taxProfiles.saveError")}</p>}
        </div>
      </form>
    </section>
  );
}
