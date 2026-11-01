import { z } from "zod";

// Validate the untrusted transport boundary without casting readonly OpenAPI responses.
export const managedUsersSchema = z.array(
  z.object({
    id: z.number().int(),
    username: z.string(),
    email: z.string(),
    role: z.enum(["read_only", "company_member", "admin"]),
    is_active: z.boolean(),
    is_protected: z.boolean(),
    must_change_password: z.boolean(),
  }),
);

export const accountDetailsSchema = z.object({
  username: z.string(),
  has_password: z.boolean(),
  must_change_password: z.boolean(),
  connections: z.array(z.object({ id: z.number().int(), provider: z.string() })),
  providers: z.array(
    z.object({
      id: z.string(),
      name: z.string(),
      connect_url: z.string().startsWith("/accounts/oidc/"),
    }),
  ),
});
