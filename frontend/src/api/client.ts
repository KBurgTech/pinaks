import createClient from "openapi-fetch";

import type { paths } from "@/api/generated/schema";

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
