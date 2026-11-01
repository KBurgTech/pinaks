import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { ApplicationDialog, Field } from "@/ui/primitives";

type CancellationInvoice = Pick<
  components["schemas"]["Invoice"],
  | "id"
  | "invoice_type"
  | "lifecycle_status"
  | "invoice_number"
  | "original_invoice_id"
  | "related_invoice_ids"
  | "correction_reason"
  | "cancellation_template_id"
  | "grand_total"
  | "currency"
  | "version"
>;

export function Cancellation({
  invoice,
  canManage,
  onOpen,
}: {
  invoice: CancellationInvoice;
  canManage: boolean;
  onOpen: (id: number) => void;
}) {
  const { t, i18n } = useTranslation("shell");
  const clients = useQueryClient();
  const [reason, setReason] = useState("");
  const [key] = useState(() => crypto.randomUUID());
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const cancellation = ["CANCELLATION", "CREDIT_NOTE"].includes(invoice.invoice_type);
  const credit = invoice.invoice_type === "CREDIT_NOTE";
  const amount = new Intl.NumberFormat(i18n.language, {
    style: "currency",
    currency: invoice.currency,
  }).format(Number(invoice.grand_total));

  async function send(issue: boolean) {
    setBusy(true);
    setFailed(false);
    setSubmitted(true);
    try {
      if (issue) {
        if (!invoice.cancellation_template_id) throw new Error("missing_template");
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
      } else {
        const { data } = await apiClient.POST("/api/v1/invoices/{invoice_id}/cancel/", {
          params: { path: { invoice_id: invoice.id } },
          body: { reason: reason.trim(), idempotency_key: key },
        });
        if (!data) throw new Error("cancellation_failed");
        clients.setQueryData(["invoice", data.id], data);
        void clients.invalidateQueries({ queryKey: ["invoice", invoice.id] });
        onOpen(data.id);
      }
      await clients.invalidateQueries({ queryKey: ["invoices"] });
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      className="my-4 grid gap-3"
      aria-label={t(
        invoice.invoice_type === "REPLACEMENT"
          ? "invoicePage.replacement"
          : credit
            ? "invoicePage.creditNote"
            : "invoicePage.cancellation",
      )}
    >
      {invoice.lifecycle_status === "CANCELLED" && (
        <p role="status">{t("invoicePage.cancelled")}</p>
      )}
      {invoice.original_invoice_id != null && (
        <>
          <button
            type="button"
            className="text-start underline"
            onClick={() => onOpen(invoice.original_invoice_id!)}
          >
            {t("invoicePage.originalInvoice", { id: invoice.original_invoice_id })}
          </button>
          <p>{invoice.correction_reason}</p>
        </>
      )}
      {(invoice.related_invoice_ids ?? []).map((id) => (
        <button key={id} type="button" className="text-start underline" onClick={() => onOpen(id)}>
          {t("invoicePage.relatedCorrection", { id })}
        </button>
      ))}
      {canManage &&
        invoice.invoice_type === "STANDARD" &&
        invoice.lifecycle_status === "ISSUED" &&
        !invoice.related_invoice_ids?.length && (
          <ApplicationDialog
            title={t("invoicePage.cancelInvoice")}
            description={t("invoicePage.cancelPreview", { number: invoice.invoice_number, amount })}
            triggerLabel={t("invoicePage.cancelInvoice")}
            closeLabel={t("invoicePage.closeCancellation")}
          >
            <form
              className="grid gap-4"
              onSubmit={(event) => {
                event.preventDefault();
                void send(false);
              }}
            >
              <Field
                label={t("invoicePage.cancellationReason")}
                inputId={`cancellation-reason-${invoice.id}`}
              >
                <textarea
                  id={`cancellation-reason-${invoice.id}`}
                  className="rounded-md border p-2"
                  required
                  maxLength={500}
                  value={reason}
                  disabled={submitted}
                  onChange={(event) => setReason(event.target.value)}
                />
              </Field>
              <button
                type="submit"
                className="rounded-md border p-2"
                disabled={busy || !reason.trim()}
              >
                {t("invoicePage.createCancellation")}
              </button>
              {failed && <p role="alert">{t("invoicePage.cancellationError")}</p>}
            </form>
          </ApplicationDialog>
        )}
      {cancellation && invoice.lifecycle_status === "DRAFT" && (
        <>
          <p>
            {t(credit ? "invoicePage.creditDraftPreview" : "invoicePage.cancellationDraftPreview", {
              amount,
            })}
          </p>
          {canManage && (
            <button
              type="button"
              className="w-fit rounded-md border p-2"
              disabled={busy || !invoice.cancellation_template_id}
              onClick={() => void send(true)}
            >
              {t(credit ? "invoicePage.issueCredit" : "invoicePage.issueCancellation")}
            </button>
          )}
          {failed && <p role="alert">{t("invoicePage.cancellationError")}</p>}
        </>
      )}
    </section>
  );
}
