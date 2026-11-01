import { z } from "zod";

// Validate JSON at the transport boundary and restore array methods erased by
// openapi-fetch's deeply readonly response mapping.
export const emailDefaultsSchema = z.object({
  language: z.enum(["en", "de"]),
  recipients: z.array(z.string()),
  templates: z.array(z.object({ id: z.number(), name: z.string() })),
});

export const emailTemplatesSchema = z.array(
  z.object({
    id: z.number(),
    code: z.string(),
    name: z.string(),
    versions: z.array(
      z.object({
        id: z.number(),
        language: z.enum(["en", "de"]),
        version: z.number(),
        status: z.enum(["draft", "published"]),
        subject: z.string(),
        body: z.string(),
        created_at: z.string(),
        published_at: z.string().nullable(),
      }),
    ),
  }),
);
