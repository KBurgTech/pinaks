import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";
import { apiClient } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { Field, PageHeader } from "@/ui/primitives";

import { emailTemplatesSchema } from "./schemas";

type Template = components["schemas"]["EmailTemplate"];
type VersionFields = { language: "en" | "de"; subject: string; body: string };

function TemplateEditor({ template }: { template: Template }) {
  const { t } = useTranslation("shell");
  const client = useQueryClient();
  const {
    register,
    handleSubmit,
    formState: { isSubmitting },
  } = useForm<VersionFields>({ defaultValues: { language: "en", subject: "", body: "" } });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<"saved" | "error" | null>(null);
  async function save(values: VersionFields) {
    setResult(null);
    try {
      const { data } = await apiClient.POST("/api/v1/email-templates/{template_id}/versions/", {
        params: { path: { template_id: template.id } },
        body: values,
      });
      if (!data) throw new Error("email_version_failed");
      setResult("saved");
      await client.invalidateQueries({ queryKey: ["email-templates"] });
    } catch {
      setResult("error");
    }
  }
  async function publish() {
    setBusy(true);
    setResult(null);
    try {
      const { data } = await apiClient.POST("/api/v1/email-templates/{template_id}/publish/", {
        params: { path: { template_id: template.id } },
      });
      if (!data) throw new Error("email_publish_failed");
      setResult("saved");
      await client.invalidateQueries({ queryKey: ["email-templates"] });
    } catch {
      setResult("error");
    } finally {
      setBusy(false);
    }
  }
  const prefix = `email-template-${template.id}`;
  return (
    <section className="my-6 grid gap-3 rounded-md border p-4">
      <h2 className="text-lg font-semibold">{template.name}</h2>
      <p>{t("email.hint", { placeholder: "{{ invoice_number }}" })}</p>
      <ul>
        {template.versions.map((version) => (
          <li key={version.id}>
            {t(`email.${version.language}`)} · v{version.version} · {t(`email.${version.status}`)}
            <p className="whitespace-pre-wrap">
              {version.subject}
              {"\n"}
              {version.body}
            </p>
          </li>
        ))}
      </ul>
      <form onSubmit={(event) => void handleSubmit(save)(event)} className="grid gap-3">
        <Field inputId={`${prefix}-language`} label={t("email.language")}>
          <select id={`${prefix}-language`} {...register("language")}>
            <option value="en">{t("email.en")}</option>
            <option value="de">{t("email.de")}</option>
          </select>
        </Field>
        <Field inputId={`${prefix}-subject`} label={t("email.subject")}>
          <input id={`${prefix}-subject`} maxLength={255} required {...register("subject")} />
        </Field>
        <Field inputId={`${prefix}-body`} label={t("email.body")}>
          <textarea id={`${prefix}-body`} required {...register("body")} />
        </Field>
        <button type="submit" disabled={isSubmitting || busy}>
          {t("email.save")}
        </button>
      </form>
      <button type="button" disabled={busy || isSubmitting} onClick={() => void publish()}>
        {t("email.publish")}
      </button>
      {result && <p role={result === "error" ? "alert" : "status"}>{t(`email.${result}`)}</p>}
    </section>
  );
}

export function EmailTemplatePage() {
  const { t } = useTranslation("shell");
  const client = useQueryClient();
  const {
    register,
    handleSubmit,
    reset,
    formState: { isSubmitting },
  } = useForm<{ code: string; name: string }>();
  const [failed, setFailed] = useState(false);
  const templates = useQuery<readonly Template[]>({
    queryKey: ["email-templates"],
    queryFn: async (): Promise<readonly Template[]> => {
      const { data } = await apiClient.GET("/api/v1/email-templates/");
      if (!data) throw new Error("email_templates_unavailable");
      return emailTemplatesSchema.parse(data);
    },
  });
  async function create(values: { code: string; name: string }) {
    setFailed(false);
    try {
      const { data } = await apiClient.POST("/api/v1/email-templates/", { body: values });
      if (!data) throw new Error("email_template_failed");
      reset();
      await client.invalidateQueries({ queryKey: ["email-templates"] });
    } catch {
      setFailed(true);
    }
  }
  return (
    <>
      <PageHeader title={t("email.heading")} />
      <form onSubmit={(event) => void handleSubmit(create)(event)} className="grid gap-3">
        <Field inputId="email-code" label={t("email.code")}>
          <input id="email-code" required maxLength={80} {...register("code")} />
        </Field>
        <Field inputId="email-name" label={t("email.name")}>
          <input id="email-name" required maxLength={120} {...register("name")} />
        </Field>
        <button type="submit" disabled={isSubmitting}>
          {t("email.create")}
        </button>
        {failed && <p role="alert">{t("email.error")}</p>}
      </form>
      {templates.isPending && <p>{t("email.loading")}</p>}
      {templates.isError && <p role="alert">{t("email.loadError")}</p>}
      {templates.data?.map((template) => (
        <TemplateEditor key={template.id} template={template} />
      ))}
    </>
  );
}
