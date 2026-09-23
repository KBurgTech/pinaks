import { apiClient } from "@/api/client";
import type { components } from "@/api/generated/schema";

type Definition = components["schemas"]["CustomFieldDefinition"];
export type Target = "customer" | "catalog_item" | "invoice" | "invoice_line";

function isDefinition(value: unknown): value is Definition {
  return (
    typeof value === "object" &&
    value !== null &&
    "key" in value &&
    typeof value.key === "string" &&
    "label_en" in value &&
    typeof value.label_en === "string" &&
    "label_de" in value &&
    typeof value.label_de === "string"
  );
}

export async function loadDefinitions(target: Target): Promise<readonly Definition[]> {
  const { data } = await apiClient.GET("/api/v1/custom-fields/", { params: { query: { target } } });
  if (Array.isArray(data) && data.every(isDefinition))
    return data.filter((field) => field.target === target);
  throw new Error("definitions_unavailable");
}
