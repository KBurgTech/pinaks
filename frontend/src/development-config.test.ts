import { describe, expect, it } from "vitest";

import { developmentServer } from "@/development-server";

describe("development server", () => {
  it("keeps Django API and account requests same-origin through the Vite proxy", () => {
    expect(developmentServer).toMatchObject({
      proxy: {
        "/accounts": "http://127.0.0.1:8000",
        "/api": "http://127.0.0.1:8000",
      },
    });
  });
});
