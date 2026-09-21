import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useForm, type FieldPath } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { Field, PageHeader } from "@/ui/primitives";

import type { components } from "@/api/generated/schema";

type CompanyProfile = components["schemas"]["CompanyProfile"];
type ErrorFields = components["schemas"]["ErrorBody"]["fields"];
type ErrorItem = components["schemas"]["ErrorItem"];

const EMPTY_PROFILE: CompanyProfile = {
  legal_name: "",
  address_line_1: "",
  address_line_2: "",
  postal_code: "",
  city: "",
  country_code: "DE",
  email: "",
  phone: "",
  tax_number: "",
  vat_identifier: "",
  company_identifier: "",
  bank_account_holder: "",
  iban: "",
  bic: "",
  payment_instructions: "",
  default_currency: "EUR",
  default_locale: "de-DE",
  default_ui_language: "de",
  default_document_language: "de",
  invoice_number_prefix: "RE-",
  invoice_number_next: 1,
  invoice_number_padding: 4,
  invoice_number_reset: "annual",
  features: {
    payment_requests: false,
    reminders: false,
    time_tracking: false,
  },
};

const FORM_FIELDS = [
  "legal_name",
  "address_line_1",
  "address_line_2",
  "postal_code",
  "city",
  "country_code",
  "email",
  "phone",
  "tax_number",
  "vat_identifier",
  "company_identifier",
  "bank_account_holder",
  "iban",
  "bic",
  "payment_instructions",
  "default_currency",
  "default_locale",
  "default_ui_language",
  "default_document_language",
  "invoice_number_prefix",
  "invoice_number_next",
  "invoice_number_padding",
  "invoice_number_reset",
  "features.payment_requests",
  "features.reminders",
  "features.time_tracking",
] as const satisfies readonly FieldPath<CompanyProfile>[];

class SubmissionError extends Error {
  constructor(readonly fields: ErrorFields) {
    super("configuration_submission_failed");
  }
}

function normalizeErrorFields(value: unknown): ErrorFields {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return {};
  }

  const fields: Record<string, ErrorItem[]> = {};
  for (const [field, messages] of Object.entries(value)) {
    if (!Array.isArray(messages)) {
      continue;
    }
    const validMessages = messages.filter(
      (message): message is ErrorItem =>
        typeof message === "object" &&
        message !== null &&
        "code" in message &&
        typeof message.code === "string" &&
        "message" in message &&
        typeof message.message === "string",
    );
    if (validMessages.length > 0) {
      fields[field] = validMessages;
    }
  }
  return fields;
}

async function loadCompanyProfile(): Promise<CompanyProfile> {
  const { data, response } = await apiClient.GET("/api/v1/configuration/company/");
  if (data !== undefined) {
    return data;
  }
  if (response.status === 404) {
    return EMPTY_PROFILE;
  }
  throw new Error("configuration_unavailable");
}

async function saveCompanyProfile(profile: CompanyProfile): Promise<CompanyProfile> {
  const { data, error } = await apiClient.PUT("/api/v1/configuration/company/", {
    body: profile,
  });
  if (data !== undefined) {
    return data;
  }
  throw new SubmissionError(normalizeErrorFields(error?.error.fields));
}

const inputClass =
  "w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm " +
  "focus-visible:outline-2 focus-visible:outline-offset-2";

export function CompanyProfileForm() {
  const { t } = useTranslation("shell");
  const [saved, setSaved] = useState(false);
  const profile = useQuery({
    queryKey: ["company-profile"],
    queryFn: loadCompanyProfile,
    retry: false,
  });
  const {
    formState: { errors },
    handleSubmit,
    register,
    reset,
    setError,
  } = useForm<CompanyProfile>({ defaultValues: EMPTY_PROFILE });

  useEffect(() => {
    if (profile.data !== undefined) {
      reset(profile.data);
    }
  }, [profile.data, reset]);

  const mutation = useMutation({
    mutationFn: saveCompanyProfile,
    onSuccess(data) {
      reset(data);
      setSaved(true);
    },
    onError(error) {
      setSaved(false);
      if (!(error instanceof SubmissionError)) {
        return;
      }
      for (const [field, messages] of Object.entries(error.fields)) {
        const formField = FORM_FIELDS.find((candidate) => candidate === field);
        const firstError = messages[0];
        if (formField !== undefined && firstError !== undefined) {
          setError(formField, {
            type: firstError.code,
            message:
              field === "legal_name" ? t("company.requiredLegalName") : t("company.invalidField"),
          });
        }
      }
    },
  });

  if (profile.isPending) {
    return <p>{t("loading")}</p>;
  }
  if (profile.isError) {
    return <p role="alert">{t("company.loadError")}</p>;
  }

  return (
    <section>
      <PageHeader title={t("company.heading")} description={t("company.description")} />
      <form
        className="grid max-w-3xl gap-8"
        onSubmit={(event) => void handleSubmit((values) => mutation.mutate(values))(event)}
      >
        <fieldset className="grid gap-4 md:grid-cols-2">
          <legend className="mb-3 text-lg font-semibold">{t("company.identity")}</legend>
          <Field
            error={errors.legal_name?.message}
            inputId="legal-name"
            label={t("company.legalName")}
          >
            <input className={inputClass} id="legal-name" {...register("legal_name")} />
          </Field>
          <Field inputId="company-identifier" label={t("company.companyIdentifier")}>
            <input
              className={inputClass}
              id="company-identifier"
              {...register("company_identifier")}
            />
          </Field>
          <Field inputId="address-line-1" label={t("company.addressLine1")}>
            <input className={inputClass} id="address-line-1" {...register("address_line_1")} />
          </Field>
          <Field inputId="address-line-2" label={t("company.addressLine2")}>
            <input className={inputClass} id="address-line-2" {...register("address_line_2")} />
          </Field>
          <Field inputId="postal-code" label={t("company.postalCode")}>
            <input className={inputClass} id="postal-code" {...register("postal_code")} />
          </Field>
          <Field inputId="city" label={t("company.city")}>
            <input className={inputClass} id="city" {...register("city")} />
          </Field>
          <Field inputId="country-code" label={t("company.countryCode")}>
            <input className={inputClass} id="country-code" {...register("country_code")} />
          </Field>
          <Field inputId="email" label={t("company.email")}>
            <input className={inputClass} id="email" type="email" {...register("email")} />
          </Field>
          <Field inputId="phone" label={t("company.phone")}>
            <input className={inputClass} id="phone" type="tel" {...register("phone")} />
          </Field>
          <Field inputId="tax-number" label={t("company.taxNumber")}>
            <input className={inputClass} id="tax-number" {...register("tax_number")} />
          </Field>
          <Field inputId="vat-identifier" label={t("company.vatIdentifier")}>
            <input className={inputClass} id="vat-identifier" {...register("vat_identifier")} />
          </Field>
        </fieldset>

        <fieldset className="grid gap-4 md:grid-cols-2">
          <legend className="mb-3 text-lg font-semibold">{t("company.payment")}</legend>
          <Field inputId="account-holder" label={t("company.accountHolder")}>
            <input
              className={inputClass}
              id="account-holder"
              {...register("bank_account_holder")}
            />
          </Field>
          <Field inputId="iban" label={t("company.iban")}>
            <input className={inputClass} id="iban" {...register("iban")} />
          </Field>
          <Field inputId="bic" label={t("company.bic")}>
            <input className={inputClass} id="bic" {...register("bic")} />
          </Field>
          <Field inputId="payment-instructions" label={t("company.paymentInstructions")}>
            <textarea
              className={inputClass}
              id="payment-instructions"
              {...register("payment_instructions")}
            />
          </Field>
        </fieldset>

        <fieldset className="grid gap-4 md:grid-cols-2">
          <legend className="mb-3 text-lg font-semibold">{t("company.defaults")}</legend>
          <Field inputId="default-currency" label={t("company.currency")}>
            <select className={inputClass} id="default-currency" {...register("default_currency")}>
              <option value="EUR">EUR</option>
            </select>
          </Field>
          <Field inputId="default-locale" label={t("company.locale")}>
            <select className={inputClass} id="default-locale" {...register("default_locale")}>
              <option value="de-DE">Deutsch (Deutschland)</option>
              <option value="en-DE">English (Germany)</option>
            </select>
          </Field>
          <Field inputId="ui-language" label={t("company.uiLanguage")}>
            <select className={inputClass} id="ui-language" {...register("default_ui_language")}>
              <option value="de">Deutsch</option>
              <option value="en">English</option>
            </select>
          </Field>
          <Field inputId="document-language" label={t("company.documentLanguage")}>
            <select
              className={inputClass}
              id="document-language"
              {...register("default_document_language")}
            >
              <option value="de">Deutsch</option>
              <option value="en">English</option>
            </select>
          </Field>
        </fieldset>

        <fieldset className="grid gap-4 md:grid-cols-2">
          <legend className="mb-3 text-lg font-semibold">{t("company.numbering")}</legend>
          <Field inputId="number-prefix" label={t("company.numberPrefix")}>
            <input
              className={inputClass}
              id="number-prefix"
              {...register("invoice_number_prefix")}
            />
          </Field>
          <Field inputId="next-number" label={t("company.nextNumber")}>
            <input
              className={inputClass}
              id="next-number"
              min="1"
              type="number"
              {...register("invoice_number_next", { valueAsNumber: true })}
            />
          </Field>
          <Field inputId="number-padding" label={t("company.numberPadding")}>
            <input
              className={inputClass}
              id="number-padding"
              max="12"
              min="1"
              type="number"
              {...register("invoice_number_padding", { valueAsNumber: true })}
            />
          </Field>
          <Field inputId="number-reset" label={t("company.numberReset")}>
            <select className={inputClass} id="number-reset" {...register("invoice_number_reset")}>
              <option value="annual">{t("company.annual")}</option>
              <option value="never">{t("company.never")}</option>
            </select>
          </Field>
        </fieldset>

        <fieldset className="grid gap-3">
          <legend className="mb-3 text-lg font-semibold">{t("company.features")}</legend>
          <label>
            <input type="checkbox" {...register("features.payment_requests")} />{" "}
            {t("paymentRequests")}
          </label>
          <label>
            <input type="checkbox" {...register("features.reminders")} /> {t("reminders")}
          </label>
          <label>
            <input type="checkbox" {...register("features.time_tracking")} /> {t("timeTracking")}
          </label>
        </fieldset>

        <div className="flex items-center gap-4">
          <button
            className="rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white"
            disabled={mutation.isPending}
            type="submit"
          >
            {t("company.save")}
          </button>
          {saved && <p role="status">{t("company.saved")}</p>}
          {mutation.isError && !(mutation.error instanceof SubmissionError) && (
            <p className="text-red-700" role="alert">
              {t("company.saveError")}
            </p>
          )}
        </div>
      </form>
    </section>
  );
}
