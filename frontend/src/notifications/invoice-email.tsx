import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { apiClient } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { ApplicationDialog, Field } from "@/ui/primitives";

import { emailDefaultsSchema } from "./schemas";

type Defaults = components["schemas"]["EmailDefaults"];
type SendBody = components["schemas"]["EmailSendRequest"];
type Command = { body: SendBody | null; queued: boolean };
type CommandProps = { command: Command; setCommand: (value: Command) => void };
type Fields = { recipients: string; language: "en" | "de"; templateId: string };

function SendForm({ invoiceId, command, setCommand }: { invoiceId: number } & CommandProps) {
  const { t } = useTranslation("shell");
  const defaults = useQuery<Defaults>({
    queryKey: ["invoice-email-defaults", invoiceId],
    queryFn: async (): Promise<Defaults> => {
      const { data } = await apiClient.GET("/api/v1/invoices/{invoice_id}/send/", {
        params: { path: { invoice_id: invoiceId } },
      });
      if (!data) throw new Error("email_defaults_unavailable");
      return emailDefaultsSchema.parse(data);
    },
  });
  if (defaults.isPending) return <p>{t("email.loading")}</p>;
  if (defaults.isError) return <p role="alert">{t("email.loadError")}</p>;
  return (
    <ReadyForm
      invoiceId={invoiceId}
      defaults={defaults.data}
      command={command}
      setCommand={setCommand}
    />
  );
}

function ReadyForm({
  invoiceId,
  defaults,
  command,
  setCommand,
}: { invoiceId: number; defaults: Defaults } & CommandProps) {
  const { t } = useTranslation("shell");
  const {
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<Fields>({
    defaultValues: {
      recipients: (command.body?.recipients ?? defaults.recipients).join(", "),
      language: command.body?.language ?? defaults.language,
      templateId: String(command.body?.template_id ?? defaults.templates[0]?.id ?? ""),
    },
  });
  const [state, setState] = useState<"ready" | "failed" | "queued">(
    command.queued ? "queued" : "ready",
  );
  // Preserve the complete command across ambiguous network failures, including dialog remounts.
  async function submit(values: Fields) {
    if (state === "queued") return;
    const inputs = {
      template_id: Number(values.templateId),
      language: values.language,
      recipients: values.recipients.split(",").map((value) => value.trim()),
    };
    let previous = command.body;
    if (
      previous &&
      (previous.language !== inputs.language ||
        previous.template_id !== inputs.template_id ||
        JSON.stringify(previous.recipients) !== JSON.stringify(inputs.recipients))
    )
      previous = null;
    const body: SendBody = {
      ...inputs,
      idempotency_key: previous?.idempotency_key ?? crypto.randomUUID(),
    };
    setCommand({ body, queued: false });
    try {
      const { data } = await apiClient.POST("/api/v1/invoices/{invoice_id}/send/", {
        params: { path: { invoice_id: invoiceId } },
        body,
      });
      if (!data) throw new Error("email_send_failed");
      setCommand({ body, queued: true });
      setState("queued");
    } catch {
      setState("failed");
    }
  }
  if (defaults.templates.length === 0) return <p role="status">{t("email.noTemplates")}</p>;
  return (
    <form className="grid gap-4" onSubmit={(event) => void handleSubmit(submit)(event)}>
      <Field
        inputId={`email-recipients-${invoiceId}`}
        label={t("email.recipients")}
        hint={t("email.recipientHint")}
      >
        <input
          id={`email-recipients-${invoiceId}`}
          required
          disabled={isSubmitting || state === "queued"}
          {...register("recipients")}
        />
      </Field>
      <Field inputId={`email-language-${invoiceId}`} label={t("email.language")}>
        <select
          id={`email-language-${invoiceId}`}
          disabled={isSubmitting || state === "queued"}
          {...register("language")}
        >
          <option value="en">{t("email.en")}</option>
          <option value="de">{t("email.de")}</option>
        </select>
      </Field>
      <Field inputId={`email-template-${invoiceId}`} label={t("email.template")}>
        <select
          id={`email-template-${invoiceId}`}
          disabled={isSubmitting || state === "queued"}
          {...register("templateId")}
        >
          {defaults.templates.map((template) => (
            <option key={template.id} value={template.id}>
              {template.name}
            </option>
          ))}
        </select>
      </Field>
      <button type="submit" disabled={isSubmitting || state === "queued"}>
        {t("email.queue")}
      </button>
      {state === "queued" && <p role="status">{t("email.queued")}</p>}
      {state === "failed" && <p role="alert">{t("email.sendError")}</p>}
    </form>
  );
}

export function InvoiceEmail({
  invoiceId,
  lifecycle,
  canSend,
}: {
  invoiceId: number;
  lifecycle: string;
  canSend: boolean;
}) {
  const { t } = useTranslation("shell");
  const [command, setCommand] = useState<Command>({ body: null, queued: false });
  if (!canSend || !["ISSUED", "CANCELLED"].includes(lifecycle)) return null;
  return (
    <ApplicationDialog
      title={t("email.send")}
      triggerLabel={t("email.send")}
      description={t("email.description")}
      closeLabel={t("email.close")}
    >
      <SendForm invoiceId={invoiceId} command={command} setCommand={setCommand} />
    </ApplicationDialog>
  );
}
