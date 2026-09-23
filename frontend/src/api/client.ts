import createClient from "openapi-fetch";

import type { components, paths } from "@/api/generated/schema";

export const apiClient = createClient<paths>({
  baseUrl: window.location.origin,
  credentials: "same-origin",
  fetch: (request) => fetch(request),
});

const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS", "TRACE"]);

function readCookie(name: string): string | undefined {
  const prefix = `${encodeURIComponent(name)}=`;

  for (const cookie of document.cookie.split(";")) {
    const value = cookie.trim();
    if (value.startsWith(prefix)) {
      return decodeURIComponent(value.slice(prefix.length));
    }
  }

  return undefined;
}

function isDocumentAsset(value: unknown): value is components["schemas"]["DocumentAsset"] {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "number" &&
    "key" in value &&
    typeof value.key === "string" &&
    "content_type" in value &&
    typeof value.content_type === "string" &&
    "size" in value &&
    typeof value.size === "number" &&
    "created_at" in value &&
    typeof value.created_at === "string"
  );
}

export async function uploadDocumentAsset(
  templateId: number,
  file: File,
): Promise<components["schemas"]["DocumentAsset"]> {
  const body = new FormData();
  body.append("file", file);
  const csrfToken = readCookie("csrftoken");
  const headers = new Headers();
  if (csrfToken !== undefined) headers.set("X-CSRFToken", csrfToken);
  const response = await fetch(`/api/v1/document-templates/${templateId}/assets/`, {
    method: "POST",
    credentials: "same-origin",
    headers,
    body,
  });
  if (!response.ok) throw new Error("document_asset_upload_failed");
  const data: unknown = await response.json();
  if (!isDocumentAsset(data)) throw new Error("document_asset_upload_failed");
  return data;
}

apiClient.use({
  onRequest({ request }) {
    if (!SAFE_METHODS.has(request.method)) {
      const csrfToken = readCookie("csrftoken");
      if (csrfToken !== undefined) {
        request.headers.set("X-CSRFToken", csrfToken);
      }
    }

    return request;
  },
});
