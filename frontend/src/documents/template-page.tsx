import { Dialog } from "@base-ui/react/dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient, uploadDocumentAsset } from "@/api/client";
import { Field, PageHeader } from "@/ui/primitives";

import type { components } from "@/api/generated/schema";

type Template = components["schemas"]["Template"];
type Version = components["schemas"]["TemplateVersion"];
type Language = "en" | "de";

const inputClass =
  "w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2";
const buttonClass =
  "rounded-md border border-neutral-300 px-3 py-2 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-50";

function isTemplate(value: unknown): value is Template {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "number" &&
    "code" in value &&
    typeof value.code === "string" &&
    "name" in value &&
    typeof value.name === "string" &&
    "created_at" in value &&
    typeof value.created_at === "string" &&
    "versions" in value &&
    Array.isArray(value.versions)
  );
}

function latest(versions: readonly Version[], language: Language): Version | undefined {
  return versions
    .filter((version) => version.language === language)
    .sort((a, b) => b.version - a.version)[0];
}

function LanguageEditor({
  templateId,
  language,
  version,
  uploadedKeys,
  onSaved,
}: {
  templateId: number;
  language: Language;
  version?: Version;
  uploadedKeys: readonly string[];
  onSaved: (version: Version) => void;
}) {
  const { t } = useTranslation("documents");
  const [html, setHtml] = useState(version?.html ?? "");
  const [css, setCss] = useState(version?.css ?? "");
  const [message, setMessage] = useState("");
  const [saving, setSaving] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [previewUrl, setPreviewUrl] = useState("");
  const [draftInvoiceId, setDraftInvoiceId] = useState("");
  const [previewError, setPreviewError] = useState(false);

  async function save() {
    setSaving(true);
    setMessage("");
    const body = {
      html,
      css,
      page_settings: { size: "A4" },
      asset_keys: [
        ...new Set([
          ...(Array.isArray(version?.asset_keys)
            ? version.asset_keys.filter((key): key is string => typeof key === "string")
            : []),
          ...uploadedKeys,
        ]),
      ],
    };
    const result =
      version === undefined
        ? await apiClient.POST("/api/v1/document-templates/{template_id}/versions/", {
            params: { path: { template_id: templateId } },
            body: { ...body, language },
          })
        : await apiClient.PATCH("/api/v1/document-templates/{template_id}/versions/{version_id}/", {
            params: { path: { template_id: templateId, version_id: version.id } },
            body,
          });
    setSaving(false);
    if (result.data !== undefined) {
      onSaved(result.data);
      setMessage(t("saved"));
    } else {
      setMessage(t("saveError"));
    }
  }

  async function preview() {
    setPreviewing(true);
    setPreviewError(false);
    setPreviewUrl("");
    try {
      const result = await apiClient.POST("/api/v1/document-templates/{template_id}/preview/", {
        params: { path: { template_id: templateId } },
        body: {
          language,
          format: "pdf",
          ...(draftInvoiceId ? { invoice_id: Number(draftInvoiceId) } : {}),
        },
      });
      if (result.data?.url) setPreviewUrl(result.data.url);
      else setPreviewError(true);
    } catch {
      setPreviewError(true);
    } finally {
      setPreviewing(false);
    }
  }

  const prefix = language === "en" ? "english" : "german";
  return (
    <section
      className="space-y-4 rounded-md border border-neutral-200 bg-white p-4"
      aria-label={t(prefix)}
    >
      <h3 className="font-semibold">{t(prefix)}</h3>
      <Field label={t(`${prefix}Html`)} inputId={`${language}-html`}>
        <textarea
          id={`${language}-html`}
          className={`${inputClass} min-h-36 font-mono`}
          value={html}
          onChange={(event) => setHtml(event.target.value)}
        />
      </Field>
      <Field label={t(`${prefix}Css`)} inputId={`${language}-css`}>
        <textarea
          id={`${language}-css`}
          className={`${inputClass} min-h-24 font-mono`}
          value={css}
          onChange={(event) => setCss(event.target.value)}
        />
      </Field>
      <button className={buttonClass} disabled={saving} onClick={() => void save()} type="button">
        {t(language === "en" ? "saveEnglish" : "saveGerman")}
      </button>
      {version && (
        <div className="space-y-2">
          <Field label={t("draftInvoiceId")} inputId={`${language}-preview-invoice-id`}>
            <input
              id={`${language}-preview-invoice-id`}
              className={inputClass}
              type="number"
              min="1"
              step="1"
              value={draftInvoiceId}
              onChange={(event) => setDraftInvoiceId(event.target.value)}
            />
          </Field>
          <button
            className={buttonClass}
            disabled={
              previewing ||
              saving ||
              html !== version.html ||
              css !== version.css ||
              (draftInvoiceId !== "" &&
                (!Number.isInteger(Number(draftInvoiceId)) || Number(draftInvoiceId) < 1))
            }
            onClick={() => void preview()}
            type="button"
          >
            {t(language === "en" ? "previewEnglish" : "previewGerman")}
          </button>
          {previewing && <p role="status">{t("previewLoading")}</p>}
          {previewError && <p role="alert">{t("previewError")}</p>}
          {previewUrl && (
            <p>
              <a className="underline" href={previewUrl} target="_blank" rel="noopener noreferrer">
                {t(language === "en" ? "openEnglishPreview" : "openGermanPreview")}
              </a>
            </p>
          )}
          <p className="text-sm text-neutral-600">{t("previewNotice")}</p>
        </div>
      )}
      {message && <p role="status">{message}</p>}
    </section>
  );
}

export function TemplatePage() {
  const { t } = useTranslation("documents");
  const queryClient = useQueryClient();
  const templates = useQuery({
    queryKey: ["document-templates"],
    queryFn: async () => {
      const { data } = await apiClient.GET("/api/v1/document-templates/");
      if (!Array.isArray(data) || !data.every(isTemplate))
        throw new Error("document_templates_unavailable");
      return data.filter(isTemplate);
    },
  });
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [selectedId, setSelectedId] = useState<number>();
  const [localTemplate, setLocalTemplate] = useState<Template>();
  const [message, setMessage] = useState("");
  const [publishing, setPublishing] = useState(false);
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const [uploadFile, setUploadFile] = useState<File>();
  const [uploadedKeys, setUploadedKeys] = useState<readonly string[]>([]);
  const [uploading, setUploading] = useState(false);

  const rows = templates.data ?? [];
  const selected =
    (localTemplate?.id === selectedId ? localTemplate : undefined) ??
    rows.find((row) => row.id === selectedId) ??
    rows[0];
  const en = selected === undefined ? undefined : latest(selected.versions, "en");
  const de = selected === undefined ? undefined : latest(selected.versions, "de");
  const canPublish = Boolean(
    en?.html.trim() && de?.html.trim() && (en?.status === "draft" || de?.status === "draft"),
  );

  function updateVersion(version: Version) {
    if (selected === undefined) return;
    setLocalTemplate({
      ...selected,
      versions: [...selected.versions.filter((row) => row.id !== version.id), version],
    });
    void queryClient.invalidateQueries({ queryKey: ["document-templates"] });
  }

  async function create() {
    setMessage("");
    const { data } = await apiClient.POST("/api/v1/document-templates/", { body: { code, name } });
    if (!isTemplate(data)) {
      setMessage(t("saveError"));
      return;
    }
    setLocalTemplate(data);
    setSelectedId(data.id);
    setCode("");
    setName("");
    void queryClient.invalidateQueries({ queryKey: ["document-templates"] });
  }

  async function publish() {
    if (selected === undefined) return;
    setPublishing(true);
    const { data } = await apiClient.POST("/api/v1/document-templates/{template_id}/publish/", {
      params: { path: { template_id: selected.id } },
    });
    setPublishing(false);
    setConfirmationOpen(false);
    if (!isTemplate(data)) {
      setMessage(t("saveError"));
      return;
    }
    setLocalTemplate(data);
    setMessage(t("publishedMessage"));
    void queryClient.invalidateQueries({ queryKey: ["document-templates"] });
  }

  async function upload() {
    if (selected === undefined || uploadFile === undefined) return;
    setUploading(true);
    try {
      const asset = await uploadDocumentAsset(selected.id, uploadFile);
      setUploadedKeys((keys) => [...keys, asset.key]);
      setUploadFile(undefined);
      setMessage(asset.key);
    } catch {
      setMessage(t("uploadError"));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="space-y-8">
      <PageHeader title={t("heading")} description={t("description")} />
      {templates.isError && <p role="alert">{t("loadError")}</p>}
      <section
        className="grid gap-4 rounded-md border border-neutral-200 bg-white p-4 sm:grid-cols-[1fr_1fr_auto]"
        aria-label={t("create")}
      >
        <Field label={t("code")} inputId="template-code">
          <input
            id="template-code"
            className={inputClass}
            value={code}
            onChange={(event) => setCode(event.target.value)}
          />
        </Field>
        <Field label={t("name")} inputId="template-name">
          <input
            id="template-name"
            className={inputClass}
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </Field>
        <button
          className={buttonClass}
          disabled={!code.trim() || !name.trim()}
          onClick={() => void create()}
          type="button"
        >
          {t("create")}
        </button>
      </section>
      {selected !== undefined && (
        <>
          <Field label={t("select")} inputId="template-select">
            <select
              id="template-select"
              className={inputClass}
              value={selected.id}
              onChange={(event) => {
                setSelectedId(Number(event.target.value));
                setLocalTemplate(undefined);
                setUploadedKeys([]);
              }}
            >
              {rows.some((row) => row.id === selected.id) ? null : (
                <option value={selected.id}>{selected.name}</option>
              )}
              {rows.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          </Field>
          <div className="grid gap-4 lg:grid-cols-2">
            <LanguageEditor
              key={`${selected.id}-en-${en?.id ?? 0}`}
              templateId={selected.id}
              language="en"
              version={en}
              uploadedKeys={uploadedKeys}
              onSaved={updateVersion}
            />
            <LanguageEditor
              key={`${selected.id}-de-${de?.id ?? 0}`}
              templateId={selected.id}
              language="de"
              version={de}
              uploadedKeys={uploadedKeys}
              onSaved={updateVersion}
            />
          </div>
          <section className="space-y-3">
            <Field label={t("asset")} inputId="template-asset">
              <input
                id="template-asset"
                type="file"
                accept="image/png,image/jpeg"
                onChange={(event) => setUploadFile(event.target.files?.[0])}
              />
            </Field>
            <button
              className={buttonClass}
              disabled={uploading || uploadFile === undefined}
              onClick={() => void upload()}
              type="button"
            >
              {t("upload")}
            </button>
          </section>
          <section className="space-y-3">
            <h2 className="text-lg font-semibold">{t("history")}</h2>
            <ul className="space-y-1">
              {[...selected.versions]
                .sort((a, b) => a.language.localeCompare(b.language) || b.version - a.version)
                .map((version) => (
                  <li key={version.id}>
                    {t(version.language === "en" ? "english" : "german")} v{version.version} —{" "}
                    {t(version.status)}
                  </li>
                ))}
            </ul>
          </section>
          <Dialog.Root open={confirmationOpen} onOpenChange={setConfirmationOpen}>
            <Dialog.Trigger
              className={buttonClass}
              disabled={!canPublish}
              onClick={() => setConfirmationOpen(true)}
            >
              {t("publish")}
            </Dialog.Trigger>
            <Dialog.Portal>
              <Dialog.Backdrop className="fixed inset-0 bg-black/40" />
              <Dialog.Viewport className="fixed inset-0 grid place-items-center p-4">
                <Dialog.Popup className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl">
                  <Dialog.Title className="text-lg font-semibold">{t("publishTitle")}</Dialog.Title>
                  <Dialog.Description className="mt-2 text-sm">
                    {t("publishDescription")}
                  </Dialog.Description>
                  <div className="mt-6 flex justify-end gap-3">
                    <Dialog.Close className={buttonClass}>{t("cancel")}</Dialog.Close>
                    <button
                      className={buttonClass}
                      disabled={publishing}
                      onClick={() => void publish()}
                      type="button"
                    >
                      {t("confirm")}
                    </button>
                  </div>
                </Dialog.Popup>
              </Dialog.Viewport>
            </Dialog.Portal>
          </Dialog.Root>
        </>
      )}
      {message && <p role="status">{message}</p>}
    </div>
  );
}
