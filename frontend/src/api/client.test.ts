import { describe, expectTypeOf, it } from "vitest";

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
});
