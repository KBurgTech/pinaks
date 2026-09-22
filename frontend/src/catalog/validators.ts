import type { components } from "@/api/generated/schema";

type TaxProfile = components["schemas"]["TaxProfile"];

export function isTaxProfile(value: unknown): value is TaxProfile {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "number" &&
    "code" in value &&
    typeof value.code === "string" &&
    "version" in value &&
    typeof value.version === "number" &&
    "name" in value &&
    typeof value.name === "string" &&
    "tax_category" in value &&
    (value.tax_category === "S" || value.tax_category === "E") &&
    "rate" in value &&
    typeof value.rate === "string" &&
    "exemption_reason_code" in value &&
    typeof value.exemption_reason_code === "string" &&
    "exemption_wording_en" in value &&
    typeof value.exemption_wording_en === "string" &&
    "exemption_wording_de" in value &&
    typeof value.exemption_wording_de === "string" &&
    "price_entry_policy" in value &&
    (value.price_entry_policy === "net" || value.price_entry_policy === "gross") &&
    "tax_column_policy" in value &&
    (value.tax_column_policy === "show" || value.tax_column_policy === "hide") &&
    "required_seller_identifiers" in value &&
    Array.isArray(value.required_seller_identifiers) &&
    "is_default" in value &&
    typeof value.is_default === "boolean" &&
    "is_current" in value &&
    typeof value.is_current === "boolean" &&
    "translation_complete" in value &&
    typeof value.translation_complete === "boolean"
  );
}
