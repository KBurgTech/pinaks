import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { Status } from "@/ui/primitives";

type PaymentInvoice = Pick<
  components["schemas"]["Invoice"],
  "id" | "lifecycle_status" | "payment_status" | "is_overdue"
>;

export function PaymentStatus({
  invoice,
  canManage,
}: {
  invoice: PaymentInvoice;
  canManage: boolean;
}) {
  const { t } = useTranslation("shell");
  const client = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const paid = invoice.payment_status === "PAID";
  async function change() {
    setBusy(true);
    setFailed(false);
    try {
      const { data } = await apiClient.POST(
        paid
          ? "/api/v1/invoices/{invoice_id}/mark-unpaid/"
          : "/api/v1/invoices/{invoice_id}/mark-paid/",
        { params: { path: { invoice_id: invoice.id } } },
      );
      if (!data) throw new Error("payment_failed");
      client.setQueryData(["invoice", invoice.id], data);
      await client.invalidateQueries({ queryKey: ["invoices"] });
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="my-3 flex flex-wrap items-center gap-3">
      <Status>
        {t(`invoicePage.${paid ? "paid" : invoice.is_overdue ? "overdue" : "unpaid"}`)}
      </Status>
      {canManage && invoice.lifecycle_status === "ISSUED" && (
        <button
          type="button"
          className="rounded-md border px-3 py-2 text-sm disabled:opacity-50"
          disabled={busy}
          onClick={() => void change()}
        >
          {t(`invoicePage.${paid ? "markUnpaid" : "markPaid"}`)}
        </button>
      )}
      {failed && <p role="alert">{t("invoicePage.paymentError")}</p>}
    </div>
  );
}
