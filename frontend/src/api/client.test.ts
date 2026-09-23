import { afterEach, describe, expect, expectTypeOf, it, vi } from "vitest";

import { apiClient, uploadDocumentAsset } from "@/api/client";
import type { components } from "@/api/generated/schema";

describe("generated API client", () => {
  it("consumes the generated probe contract", () => {
    const requestProbe = () => apiClient.GET("/api/v1/probe/");
    const probe: components["schemas"]["Probe"] = {
      checks: [],
      status: "ok",
    };

    expectTypeOf(requestProbe).toBeFunction();
    expectTypeOf(probe.status).toEqualTypeOf<string>();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.cookie = "csrftoken=; Max-Age=0; Path=/";
  });

  it("uploads document assets with CSRF and rejects malformed responses", async () => {
    document.cookie = "csrftoken=asset-csrf; Path=/";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ key: 123 }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      uploadDocumentAsset(7, new File(["image"], "logo.png", { type: "image/png" })),
    ).rejects.toThrow("document_asset_upload_failed");
    const path = fetchMock.mock.calls[0]?.[0] as string;
    const options = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect(path).toBe("/api/v1/document-templates/7/assets/");
    expect(options.credentials).toBe("same-origin");
    expect(options.headers).toBeInstanceOf(Headers);
    if (!(options.headers instanceof Headers)) throw new Error("missing upload headers");
    expect(options.headers.get("X-CSRFToken")).toBe("asset-csrf");
    expect(options.body).toBeInstanceOf(FormData);
  });

  it("sends the Django CSRF cookie on unsafe same-origin requests", async () => {
    document.cookie = "csrftoken=csrf-test-value; Path=/";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await apiClient.POST("/api/v1/probe/" as never);

    const request = fetchMock.mock.calls[0]?.[0] as Request;
    expect(request.credentials).toBe("same-origin");
    expect(request.headers.get("X-CSRFToken")).toBe("csrf-test-value");
  });
});
