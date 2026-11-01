import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { ApplicationDialog, Field } from "@/ui/primitives";

type Invoice = Pick<
  components["schemas"]["Invoice"],
  | "id"
  | "invoice_type"
  | "lifecycle_status"
  | "invoice_number"
  | "grand_total"
  | "currency"
  | "version"
  | "cancellation_template_id"
>;

export function Replacement({
  invoice,
  canManage,
  onOpen,
  hasUnsavedChanges = false,
}: {
  invoice: Invoice;
  canManage: boolean;
  onOpen: (id: number) => void;
  hasUnsavedChanges?: boolean;
}) {
  const { t, i18n } = useTranslation("shell");
  const clients = useQueryClient();
  const [reason, setReason] = useState("");
  const [key] = useState(() => crypto.randomUUID());
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const amount = new Intl.NumberFormat(i18n.language, {
    style: "currency",
    currency: invoice.currency,
  }).format(Number(invoice.grand_total));

  async function create() {
    setBusy(true);
    setFailed(false);
    setSubmitted(true);
    try {
      const { data } = await apiClient.POST("/api/v1/invoices/{invoice_id}/correct/", {
        params: { path: { invoice_id: invoice.id } },
        body: { reason: reason.trim(), idempotency_key: key },
      });
      if (!data) throw new Error("replacement_failed");
      clients.setQueryData(["invoice", data.id], data);
      void clients.invalidateQueries({ queryKey: ["invoice", invoice.id] });
      await clients.invalidateQueries({ queryKey: ["invoices"] });
      onOpen(data.id);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  async function issue() {
    if (!invoice.cancellation_template_id || hasUnsavedChanges) return;
    setBusy(true);
    setFailed(false);
    try {
      const { data } = await apiClient.POST("/api/v1/invoices/{invoice_id}/issue/", {
        params: { path: { invoice_id: invoice.id } },
        body: {
          expected_version: invoice.version,
          template_id: invoice.cancellation_template_id,
          idempotency_key: key,
        },
      });
      if (!data) throw new Error("issuance_failed");
      clients.setQueryData(["invoice", invoice.id], data);
      await clients.invalidateQueries({ queryKey: ["invoices"] });
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  if (invoice.invoice_type === "REPLACEMENT") {
    return (
      <section className="my-4 grid gap-3" aria-label={t("invoicePage.replacement")}>
        <p role="status">
          {t(
            invoice.lifecycle_status === "DRAFT"
              ? "invoicePage.replacementDraftPreview"
              : "invoicePage.replacement",
            { amount },
          )}
        </p>
        {canManage && invoice.lifecycle_status === "DRAFT" && (
          <>
            <button
              type="button"
              className="w-fit rounded-md border p-2"
              disabled={busy || hasUnsavedChanges || !invoice.cancellation_template_id}
              onClick={() => void issue()}
            >
              {t("invoicePage.issueReplacement")}
            </button>
            {hasUnsavedChanges && <p>{t("invoicePage.saveReplacementFirst")}</p>}
          </>
        )}
        {failed && <p role="alert">{t("invoicePage.replacementError")}</p>}
      </section>
    );
  }
  if (!canManage || invoice.invoice_type !== "STANDARD" || invoice.lifecycle_status !== "CANCELLED")
    return null;
  return (
    <ApplicationDialog
      title={t("invoicePage.createReplacement")}
      description={t("invoicePage.replacementPreview", { number: invoice.invoice_number, amount })}
      triggerLabel={t("invoicePage.createReplacement")}
      closeLabel={t("invoicePage.closeCancellation")}
    >
      <form
        className="grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void create();
        }}
      >
        <Field
          label={t("invoicePage.replacementReason")}
          inputId={`replacement-reason-${invoice.id}`}
        >
          <textarea
            id={`replacement-reason-${invoice.id}`}
            className="rounded-md border p-2"
            required
            maxLength={500}
            value={reason}
            disabled={submitted}
            onChange={(event) => setReason(event.target.value)}
          />
        </Field>
        <button type="submit" className="rounded-md border p-2" disabled={busy || !reason.trim()}>
          {t("invoicePage.createReplacementDraft")}
        </button>
        {failed && <p role="alert">{t("invoicePage.replacementError")}</p>}
      </form>
    </ApplicationDialog>
  );
}
