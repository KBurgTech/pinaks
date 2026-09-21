import { afterEach, describe, expect, expectTypeOf, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import type { components } from "@/api/generated/schema";

describe("generated API client", () => {
  it("consumes the generated probe contract", () => {
    type GetPath = Parameters<typeof apiClient.GET>[0];
    const probe: components["schemas"]["Probe"] = {
      checks: [],
      status: "ok",
    };

    expectTypeOf<"/api/v1/probe/">().toMatchTypeOf<GetPath>();
    expectTypeOf(probe.status).toEqualTypeOf<string>();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.cookie = "csrftoken=; Max-Age=0; Path=/";
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
