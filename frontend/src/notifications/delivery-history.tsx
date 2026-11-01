import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { apiClient } from "@/api/client";
import { emailDeliveriesSchema } from "./schemas";

export function DeliveryHistory({ invoiceId }: { invoiceId: number }) {
  const { t, i18n } = useTranslation("shell");
  const history = useQuery({
    queryKey: ["invoice-email-history", invoiceId],
    queryFn: async () => {
      const { data } = await apiClient.GET("/api/v1/invoices/{invoice_id}/emails/", {
        params: { path: { invoice_id: invoiceId } },
      });
      return emailDeliveriesSchema.parse(data);
    },
    refetchInterval: 10_000,
  });
  const date = (value: string) => new Date(value).toLocaleString(i18n.language);
  return (
    <section aria-label={t("email.deliveryHistory")} className="grid gap-3">
      <h3>{t("email.deliveryHistory")}</h3>
      {history.isPending && <p role="status">{t("email.loading")}</p>}
      {history.isError && <p role="status">{t("email.historyError")}</p>}
      {history.data?.length === 0 && <p>{t("email.noDeliveries")}</p>}
      {history.data?.map((message) => (
        <article key={message.id} className="rounded border p-3">
          <p>
            {date(message.created_at)} · {t(`email.${message.language}`)} ·{" "}
            <span>{t(`email.deliveryStates.${message.delivery_state}`)}</span>
          </p>
          {message.next_attempt_at && (
            <p>{t("email.nextAttempt", { date: date(message.next_attempt_at) })}</p>
          )}
          <ol>
            {message.attempts.map((attempt) => (
              <li key={attempt.id}>
                {date(attempt.started_at)} ·{" "}
                <span>{t(`email.attemptOutcomes.${attempt.outcome}`)}</span>
                {attempt.finished_at && <> · {date(attempt.finished_at)}</>}
                {attempt.response_code && <> · SMTP {attempt.response_code}</>}
                {attempt.failure_code && (
                  <p>
                    {t(`email.deliveryErrors.${attempt.failure_code}`, {
                      defaultValue: t("email.deliveryErrors.other"),
                    })}
                  </p>
                )}
              </li>
            ))}
          </ol>
        </article>
      ))}
    </section>
  );
}
