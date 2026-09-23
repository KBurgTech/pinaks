import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { apiClient } from "@/api/client";
import { loadDefinitions, type Target } from "@/custom-fields/definitions";

import type { components } from "@/api/generated/schema";

type Definition = components["schemas"]["CustomFieldDefinition"];
type DefinitionRequest = components["schemas"]["CustomFieldDefinitionRequest"];

const inputClass = "w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm";

function primitiveText(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function choiceOptions(value: unknown): { code: string; label_en: string; label_de: string }[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (choice: unknown): choice is { code: string; label_en: string; label_de: string } =>
      typeof choice === "object" &&
      choice !== null &&
      "code" in choice &&
      typeof choice.code === "string" &&
      "label_en" in choice &&
      typeof choice.label_en === "string" &&
      "label_de" in choice &&
      typeof choice.label_de === "string",
  );
}

function label(definition: Definition, language: string): string {
  return language === "de" ? definition.label_de : definition.label_en;
}

function help(definition: Definition, language: string): string | undefined {
  return language === "de" ? definition.help_de : definition.help_en;
}

export function CustomFields({
  target,
  values,
  onChange,
  readOnly = false,
  showSensitive = false,
}: {
  target: Target;
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
  readOnly?: boolean;
  showSensitive?: boolean;
}) {
  const { t, i18n } = useTranslation("shell");
  const definitions = useQuery({
    queryKey: ["custom-fields", target],
    queryFn: () => loadDefinitions(target),
  });
  if (definitions.isPending) return null;
  if (definitions.isError) return <p role="alert">{t("customFields.loadError")}</p>;
  const visible = definitions.data.filter((field) => showSensitive || !field.is_sensitive);
  if (visible.length === 0) return null;
  const language = i18n.resolvedLanguage === "de" ? "de" : "en";
  return (
    <fieldset className="grid gap-4 md:grid-cols-2">
      <legend className="mb-3 text-lg font-semibold">{t("customFields.formHeading")}</legend>
      {visible.map((field) => {
        const id = `custom-${target}-${field.key}`;
        const current = values[field.key];
        const update = (value: unknown) => onChange({ ...values, [field.key]: value });
        const fieldLabel = label(field, language);
        const hint = help(field, language);
        return (
          <div key={field.id} className="grid gap-1">
            <label className="text-sm font-medium" htmlFor={id}>
              {fieldLabel}
            </label>
            {field.data_type === "boolean" ? (
              <input
                id={id}
                type="checkbox"
                disabled={readOnly}
                checked={current === true}
                onChange={(event) => update(event.target.checked)}
              />
            ) : field.data_type === "choice" ? (
              <select
                id={id}
                className={inputClass}
                disabled={readOnly}
                value={primitiveText(current)}
                onChange={(event) => update(event.target.value || null)}
              >
                <option value="">—</option>
                {choiceOptions(field.choices).map((choice) => (
                  <option key={choice.code} value={choice.code}>
                    {language === "de" ? choice.label_de : choice.label_en}
                  </option>
                ))}
              </select>
            ) : field.data_type === "long_text" ? (
              <textarea
                id={id}
                className={inputClass}
                disabled={readOnly}
                value={primitiveText(current)}
                onChange={(event) => update(event.target.value || null)}
              />
            ) : (
              <input
                id={id}
                className={inputClass}
                disabled={readOnly}
                type={
                  field.is_sensitive ? "password" : field.data_type === "date" ? "date" : "text"
                }
                inputMode={
                  field.data_type === "integer" || field.data_type === "decimal"
                    ? "decimal"
                    : undefined
                }
                value={primitiveText(current)}
                onChange={(event) => {
                  const raw = event.target.value;
                  update(
                    raw === ""
                      ? null
                      : field.data_type === "integer" && /^-?\d+$/.test(raw)
                        ? Number(raw)
                        : raw,
                  );
                }}
              />
            )}
            {hint && <p className="text-sm text-neutral-600">{hint}</p>}
          </div>
        );
      })}
    </fieldset>
  );
}

const emptyDefinition: DefinitionRequest = {
  key: "",
  target: "customer",
  data_type: "text",
  label_en: "",
  label_de: "",
  help_en: "",
  help_de: "",
  required: false,
  display_order: 0,
  visibility: "internal",
  search_mode: "none",
  is_sensitive: false,
  choices: [],
};

export function CustomFieldsAdmin() {
  const { t, i18n } = useTranslation("shell");
  const [target, setTarget] = useState<Target>("customer");
  const [draft, setDraft] = useState<DefinitionRequest>(emptyDefinition);
  const [choiceLines, setChoiceLines] = useState("");
  const [editingId, setEditingId] = useState<number | null>(null);
  const queryClient = useQueryClient();
  const definitions = useQuery({
    queryKey: ["custom-fields", target],
    queryFn: () => loadDefinitions(target),
  });
  const publish = useMutation({
    mutationFn: async () => {
      const choices =
        draft.data_type === "choice"
          ? choiceLines
              .split("\n")
              .filter(Boolean)
              .map((line) => {
                const [code = "", label_en = "", label_de = ""] = line
                  .split("|")
                  .map((part) => part.trim());
                return { code, label_en, label_de };
              })
          : [];
      const rawDefault = draft.default_value;
      const defaultValue =
        draft.data_type === "integer" &&
        typeof rawDefault === "string" &&
        /^-?\d+$/.test(rawDefault)
          ? Number(rawDefault)
          : draft.data_type === "boolean" && (rawDefault === "true" || rawDefault === "false")
            ? rawDefault === "true"
            : rawDefault;
      const body = { ...draft, target, choices, default_value: defaultValue };
      const { data, error } =
        editingId === null
          ? await apiClient.POST("/api/v1/custom-fields/", { body })
          : await apiClient.PATCH("/api/v1/custom-fields/{field_id}/", {
              params: { path: { field_id: editingId } },
              body,
            });
      if (error || !data) throw new Error("publish_failed");
      return data;
    },
    onSuccess: () => {
      setDraft({ ...emptyDefinition, target });
      setEditingId(null);
      setChoiceLines("");
      void queryClient.invalidateQueries({ queryKey: ["custom-fields", target] });
    },
  });
  const retire = useMutation({
    mutationFn: async (id: number) => {
      const { error } = await apiClient.DELETE("/api/v1/custom-fields/{field_id}/", {
        params: { path: { field_id: id } },
      });
      if (error) throw new Error("retire_failed");
    },
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["custom-fields", target] }),
  });
  const edit = (field: Definition) => {
    setEditingId(field.id);
    setDraft({
      key: field.key,
      target: field.target,
      data_type: field.data_type,
      label_en: field.label_en,
      label_de: field.label_de,
      help_en: field.help_en ?? "",
      help_de: field.help_de ?? "",
      required: field.required ?? false,
      default_value: field.default_value,
      display_order: field.display_order ?? 0,
      visibility: field.visibility ?? "internal",
      search_mode: field.search_mode ?? "none",
      is_sensitive: field.is_sensitive ?? false,
    });
    setChoiceLines(
      choiceOptions(field.choices)
        .map((choice) => `${choice.code} | ${choice.label_en} | ${choice.label_de}`)
        .join("\n"),
    );
  };
  const set = <K extends keyof DefinitionRequest>(key: K, value: DefinitionRequest[K]) =>
    setDraft((previous) => ({ ...previous, [key]: value }));
  return (
    <section className="grid max-w-3xl gap-6">
      <div>
        <h2 className="text-2xl font-semibold">{t("customFields.heading")}</h2>
        <p>{t("customFields.description")}</p>
      </div>
      <label className="grid gap-1">
        {t("customFields.target")}
        <select
          className={inputClass}
          disabled={editingId !== null}
          value={target}
          onChange={(event) => {
            const next = event.target.value as Target;
            setTarget(next);
            setDraft({ ...emptyDefinition, target: next });
          }}
        >
          <option value="customer">{t("customFields.customer")}</option>
          <option value="catalog_item">{t("customFields.catalogItem")}</option>
          <option value="invoice">{t("customFields.invoice")}</option>
          <option value="invoice_line">{t("customFields.invoiceLine")}</option>
        </select>
      </label>
      {definitions.isError && <p role="alert">{t("customFields.loadError")}</p>}
      {definitions.data &&
        (definitions.data.length ? (
          <ul className="grid gap-2">
            {definitions.data.map((field) => (
              <li key={field.id} className="flex items-center justify-between rounded border p-3">
                <span>
                  {field.key} — {label(field, i18n.resolvedLanguage ?? "en")}
                </span>
                <div className="flex gap-3">
                  <button type="button" onClick={() => edit(field)}>
                    {t("customFields.edit")}
                  </button>
                  <button type="button" onClick={() => retire.mutate(field.id)}>
                    {t("customFields.retire")}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p>{t("customFields.empty")}</p>
        ))}
      <form
        className="grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          publish.mutate();
        }}
      >
        <label>
          {t("customFields.machineKey")}
          <input
            className={inputClass}
            required
            disabled={editingId !== null}
            value={draft.key}
            onChange={(event) => set("key", event.target.value)}
          />
        </label>
        <label>
          {t("customFields.englishLabel")}
          <input
            className={inputClass}
            required
            value={draft.label_en}
            onChange={(event) => set("label_en", event.target.value)}
          />
        </label>
        <label>
          {t("customFields.germanLabel")}
          <input
            className={inputClass}
            required
            value={draft.label_de}
            onChange={(event) => set("label_de", event.target.value)}
          />
        </label>
        <label>
          {t("customFields.englishHelp")}
          <input
            className={inputClass}
            value={draft.help_en}
            onChange={(event) => set("help_en", event.target.value)}
          />
        </label>
        <label>
          {t("customFields.germanHelp")}
          <input
            className={inputClass}
            value={draft.help_de}
            onChange={(event) => set("help_de", event.target.value)}
          />
        </label>
        <label>
          {t("customFields.type")}
          <select
            className={inputClass}
            disabled={editingId !== null}
            value={draft.data_type}
            onChange={(event) =>
              set("data_type", event.target.value as DefinitionRequest["data_type"])
            }
          >
            {(
              ["text", "long_text", "integer", "decimal", "boolean", "date", "choice"] as const
            ).map((kind) => (
              <option key={kind} value={kind}>
                {t(`customFields.${kind === "long_text" ? "longText" : kind}`)}
              </option>
            ))}
          </select>
        </label>
        {draft.data_type === "choice" && (
          <label>
            {t("customFields.choices")}
            <textarea
              className={inputClass}
              value={choiceLines}
              onChange={(event) => setChoiceLines(event.target.value)}
            />
          </label>
        )}
        <label>
          {t("customFields.defaultValue")}
          <input
            className={inputClass}
            value={primitiveText(draft.default_value)}
            onChange={(event) => set("default_value", event.target.value || null)}
          />
        </label>
        <label>
          {t("customFields.displayOrder")}
          <input
            className={inputClass}
            type="number"
            min="0"
            value={draft.display_order}
            onChange={(event) => set("display_order", Number(event.target.value))}
          />
        </label>
        <label>
          {t("customFields.visibility")}
          <select
            className={inputClass}
            value={draft.visibility}
            onChange={(event) =>
              set("visibility", event.target.value as DefinitionRequest["visibility"])
            }
          >
            <option value="internal">{t("customFields.internal")}</option>
            <option value="document">{t("customFields.document")}</option>
          </select>
        </label>
        <label>
          {t("customFields.searchMode")}
          <select
            className={inputClass}
            value={draft.search_mode}
            onChange={(event) =>
              set("search_mode", event.target.value as DefinitionRequest["search_mode"])
            }
          >
            <option value="none">{t("customFields.none")}</option>
            <option value="exact">{t("customFields.exact")}</option>
            <option value="range">{t("customFields.range")}</option>
            <option value="text">{t("customFields.textSearch")}</option>
          </select>
        </label>
        <label>
          <input
            type="checkbox"
            checked={draft.required}
            onChange={(event) => set("required", event.target.checked)}
          />{" "}
          {t("customFields.required")}
        </label>
        <label>
          <input
            type="checkbox"
            checked={draft.is_sensitive}
            onChange={(event) => set("is_sensitive", event.target.checked)}
          />{" "}
          {t("customFields.sensitive")}
        </label>
        {publish.isError && <p role="alert">{t("customFields.saveError")}</p>}
        <button className="rounded bg-neutral-900 px-3 py-2 text-white" type="submit">
          {t(editingId === null ? "customFields.publish" : "customFields.save")}
        </button>
        {editingId !== null && (
          <button
            type="button"
            onClick={() => {
              setEditingId(null);
              setDraft({ ...emptyDefinition, target });
              setChoiceLines("");
            }}
          >
            {t("customFields.cancel")}
          </button>
        )}
      </form>
    </section>
  );
}
