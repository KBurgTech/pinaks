import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { CatalogPage } from "@/catalog/catalog-page";
import { CompanyProfileForm } from "@/configuration/company-profile-form";
import { TaxProfileForm } from "@/configuration/tax-profile-form";
import { CustomerPage } from "@/customers/customer-page";
import { CustomFieldsAdmin } from "@/custom-fields/custom-fields";
import { TemplatePage } from "@/documents/template-page";
import { setUiLanguage } from "@/i18n";
import { InvoicePage } from "@/invoices/invoice-page";

import type { components } from "@/api/generated/schema";

type Capabilities = components["schemas"]["Capabilities"];

async function loadCapabilities(): Promise<Capabilities | null> {
  const { data, response } = await apiClient.GET("/api/v1/capabilities/");
  if (data !== undefined) {
    return data;
  }
  if (response.status === 403) {
    return null;
  }

  throw new Error("capabilities_unavailable");
}

function LanguageSwitch() {
  const { i18n, t } = useTranslation("shell");
  const language = i18n.resolvedLanguage === "de" ? "de" : "en";
  const nextLanguage = language === "en" ? "de" : "en";

  return (
    <button
      className="rounded-md border border-neutral-300 px-3 py-2 text-sm font-medium hover:bg-neutral-100 focus-visible:outline-2 focus-visible:outline-offset-2"
      onClick={() => void setUiLanguage(nextLanguage)}
      type="button"
    >
      {t(nextLanguage === "de" ? "switchToGerman" : "switchToEnglish")}
    </button>
  );
}

function Shell() {
  const { t } = useTranslation("shell");
  const capabilities = useQuery({
    queryKey: ["capabilities"],
    queryFn: loadCapabilities,
    retry: false,
  });

  if (capabilities.isPending) {
    return <p className="p-6">{t("loading")}</p>;
  }

  if (capabilities.isError) {
    return (
      <p className="p-6" role="alert">
        {t("loadError")}
      </p>
    );
  }

  if (capabilities.data === null) {
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-6 px-6">
        <h1 className="text-3xl font-semibold">{t("signInHeading")}</h1>
        <a
          className="w-fit rounded-md bg-neutral-900 px-4 py-2 text-white"
          href="/accounts/login/?next=/app/"
        >
          {t("signIn")}
        </a>
      </main>
    );
  }

  const canAdminister = capabilities.data.capabilities.administration === true;
  const canCreateDrafts = capabilities.data.capabilities.draft_mutation === true;

  return (
    <div className="min-h-screen bg-neutral-50 text-neutral-950">
      <header className="border-b border-neutral-200 bg-white">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
          <a className="text-xl font-semibold tracking-tight" href="/app/">
            {t("brand")}
          </a>
          <LanguageSwitch />
        </div>
      </header>
      <div className="mx-auto grid max-w-7xl gap-8 px-6 py-8 md:grid-cols-[14rem_1fr]">
        <nav aria-label={t("mainNavigation")}>
          <ul className="space-y-1">
            <li>
              <a href="/app/customers/">{t("customers")}</a>
            </li>
            <li>
              <a href="/app/catalog/">{t("catalog")}</a>
            </li>
            <li>
              <a href="/app/invoices/">{t("invoices")}</a>
            </li>
            {canCreateDrafts && (
              <li>
                <a href="/app/invoices/new">{t("newInvoice")}</a>
              </li>
            )}
            {capabilities.data.features.payment_requests && (
              <li>
                <a href="/app/payment-requests/">{t("paymentRequests")}</a>
              </li>
            )}
            {capabilities.data.features.reminders && (
              <li>
                <a href="/app/reminders/">{t("reminders")}</a>
              </li>
            )}
            {capabilities.data.features.time_tracking && (
              <li>
                <a href="/app/time-tracking/">{t("timeTracking")}</a>
              </li>
            )}
            {canAdminister && (
              <li>
                <a href="/app/settings/">{t("settings")}</a>
              </li>
            )}
            {canAdminister && (
              <li>
                <a href="/app/custom-fields/">{t("customFields.heading")}</a>
              </li>
            )}
            {canAdminister && (
              <li>
                <a href="/app/document-templates/">{t("documentsNav")}</a>
              </li>
            )}
            {canAdminister && (
              <li>
                <a href="/app/users/">{t("users")}</a>
              </li>
            )}
          </ul>
        </nav>
        <main>
          {window.location.pathname === "/app/customers/" ? (
            <CustomerPage canMutate={canCreateDrafts} />
          ) : window.location.pathname === "/app/catalog/" ? (
            <CatalogPage canMutate={canCreateDrafts} />
          ) : window.location.pathname.startsWith("/app/invoices/") ? (
            <InvoicePage canMutate={canCreateDrafts} canAdminister={canAdminister} />
          ) : canAdminister && window.location.pathname === "/app/document-templates/" ? (
            <TemplatePage />
          ) : canAdminister && window.location.pathname === "/app/custom-fields/" ? (
            <CustomFieldsAdmin />
          ) : canAdminister && window.location.pathname === "/app/settings/" ? (
            <>
              <CompanyProfileForm />
              <TaxProfileForm />
            </>
          ) : (
            <>
              <h1 className="text-3xl font-semibold tracking-tight">{t("workspaceHeading")}</h1>
              <p className="mt-2 text-neutral-600">{t("workspaceDescription")}</p>
            </>
          )}
        </main>
      </div>
    </div>
  );
}

export function App() {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: 30_000 } } }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <Shell />
    </QueryClientProvider>
  );
}
