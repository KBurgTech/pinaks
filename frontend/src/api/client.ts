import createClient from "openapi-fetch";

import type { paths } from "@/api/generated/schema";

export const apiClient = createClient<paths>({
  credentials: "same-origin",
});
