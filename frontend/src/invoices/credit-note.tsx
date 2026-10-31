import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { ApplicationDialog, Field } from "@/ui/primitives";

type CreditSource = Pick<
  components["schemas"]["Invoice"],
  "id" | "invoice_type" | "lifecycle_status" | "invoice_number"
> & {
  lines: readonly Pick<
    components["schemas"]["InvoiceLine"],
    "position" | "description" | "quantity" | "unit_price"
  >[];
};

export function CreditNote({
  invoice,
  canManage,
  onOpen,
}: {
  invoice: CreditSource;
  canManage: boolean;
  onOpen: (id: number) => void;
}) {
  const { t } = useTranslation("shell");
  const clients = useQueryClient();
  const [reason, setReason] = useState("");
  const [allocations, setAllocations] = useState<
    Record<number, { quantity: string; unit_price: string }>
  >({});
  const [identity] = useState(() => crypto.randomUUID());
  const [busy, setBusy] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [failed, setFailed] = useState(false);
  if (!canManage || invoice.invoice_type !== "STANDARD" || invoice.lifecycle_status !== "ISSUED")
    return null;
  const selected = invoice.lines.flatMap((line) => {
    const row = allocations[line.position];
    return row && Number(row.quantity) > 0 ? [{ position: line.position, ...row }] : [];
  });

  async function submit() {
    setBusy(true);
    setFailed(false);
    setSubmitted(true);
    try {
      const { data } = await apiClient.POST("/api/v1/invoices/{invoice_id}/credit-notes/", {
        params: { path: { invoice_id: invoice.id } },
        body: { reason: reason.trim(), idempotency_key: identity, lines: selected },
      });
      if (!data) throw new Error("credit_failed");
      clients.setQueryData(["invoice", data.id], data);
      void clients.invalidateQueries({ queryKey: ["invoice", invoice.id] });
      void clients.invalidateQueries({ queryKey: ["invoices"] });
      onOpen(data.id);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <ApplicationDialog
      title={t("invoicePage.createCredit")}
      description={t("invoicePage.creditPreview", { number: invoice.invoice_number })}
      triggerLabel={t("invoicePage.createCredit")}
      closeLabel={t("invoicePage.closeCancellation")}
    >
      <form
        className="grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <Field label={t("invoicePage.creditReason")} inputId={`credit-reason-${invoice.id}`}>
          <textarea
            id={`credit-reason-${invoice.id}`}
            required
            maxLength={500}
            disabled={submitted}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            className="rounded-md border p-2"
          />
        </Field>
        {invoice.lines.map((line) => (
          <fieldset
            key={line.position}
            className="grid gap-2 rounded-md border p-3"
            disabled={submitted}
          >
            <legend>{line.description}</legend>
            <Field
              label={t("invoicePage.creditQuantity", { description: line.description })}
              inputId={`credit-qty-${line.position}`}
            >
              <input
                id={`credit-qty-${line.position}`}
                type="number"
                min="0"
                max={line.quantity}
                step="0.0001"
                value={allocations[line.position]?.quantity ?? "0"}
                onChange={(event) =>
                  setAllocations({
                    ...allocations,
                    [line.position]: {
                      quantity: event.target.value,
                      unit_price: allocations[line.position]?.unit_price ?? line.unit_price,
                    },
                  })
                }
                className="rounded-md border p-2"
              />
            </Field>
            <Field
              label={t("invoicePage.creditPrice", { description: line.description })}
              inputId={`credit-price-${line.position}`}
            >
              <input
                id={`credit-price-${line.position}`}
                type="number"
                min="0"
                max={line.unit_price}
                step="0.01"
                required
                value={allocations[line.position]?.unit_price ?? line.unit_price}
                onChange={(event) =>
                  setAllocations({
                    ...allocations,
                    [line.position]: {
                      quantity: allocations[line.position]?.quantity ?? "0",
                      unit_price: event.target.value,
                    },
                  })
                }
                className="rounded-md border p-2"
              />
            </Field>
          </fieldset>
        ))}
        <button
          type="submit"
          disabled={busy || !reason.trim() || selected.length === 0}
          className="rounded-md border p-2"
        >
          {t("invoicePage.createCreditDraft")}
        </button>
        {failed && <p role="alert">{t("invoicePage.creditError")}</p>}
      </form>
    </ApplicationDialog>
  );
}
