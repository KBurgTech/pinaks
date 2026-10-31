import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import type { components } from "@/api/generated/schema";

export function IssuedDocuments({ invoiceId }: { invoiceId: number }) {
  const { t } = useTranslation();
  const clients = useQueryClient();
  const documents = useQuery({
    queryKey: ["invoice-documents", invoiceId],
    queryFn: async () => {
      const { data } = await apiClient.GET("/api/v1/invoices/{invoice_id}/documents/", {
        params: { path: { invoice_id: invoiceId } },
      });
      if (!data) throw new Error("documents_unavailable");
      const artifacts: unknown = data.artifacts;
      if (
        !Array.isArray(artifacts) ||
        !artifacts.every(
          (
            artifact: unknown,
          ): artifact is Pick<components["schemas"]["ArtifactMetadata"], "kind"> =>
            typeof artifact === "object" &&
            artifact !== null &&
            "kind" in artifact &&
            (artifact.kind === "pdf" || artifact.kind === "xml" || artifact.kind === "report"),
        )
      )
        throw new Error("documents_unavailable");
      return { ...data, artifacts };
    },
    refetchInterval: (query) =>
      query.state.data?.lifecycle_status === "ISSUING" &&
      query.state.data.operation_state !== "failed"
        ? 2000
        : false,
    refetchIntervalInBackground: true,
  });
  const state = documents.data;
  useEffect(() => {
    if (state?.lifecycle_status === "ISSUED") {
      void clients.invalidateQueries({ queryKey: ["invoice", invoiceId] });
    }
  }, [state?.lifecycle_status, clients, invoiceId]);
  if (documents.isPending) return <p role="status">{t("invoicePage.documentsLoading")}</p>;
  if (documents.isError)
    return (
      <p role="alert">
        {t("invoicePage.documentsError")}{" "}
        <button type="button" onClick={() => void documents.refetch()}>
          {t("invoicePage.reload")}
        </button>
      </p>
    );
  if (!state) return null;
  const failed = state.operation_state === "failed";
  return (
    <section className="mb-6 grid gap-3" aria-label={t("invoicePage.documents")}>
      <p
        role={
          failed || (state.lifecycle_status === "ISSUED" && !state.healthy) ? "alert" : "status"
        }
      >
        {t(
          `invoicePage.${
            state.lifecycle_status === "ISSUED"
              ? state.healthy
                ? "documentsIssued"
                : "documentsUnhealthy"
              : failed
                ? "documentsFailed"
                : state.failure_code
                  ? "documentsRetrying"
                  : "documentsGenerating"
          }`,
        )}
      </p>
      {state.healthy && (
        <div className="flex flex-wrap gap-4">
          {state.artifacts.map((artifact) => (
            <a
              className="underline"
              download
              key={artifact.kind}
              href={`/api/v1/invoices/${invoiceId}/documents/${artifact.kind}/`}
            >
              {t(`invoicePage.download_${artifact.kind}`)}
            </a>
          ))}
        </div>
      )}
    </section>
  );
}
