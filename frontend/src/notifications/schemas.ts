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

export const emailDeliveriesSchema = z.array(
  z.object({
    id: z.string(),
    language: z.enum(["en", "de"]),
    delivery_state: z.enum(["queued", "sending", "sent", "failed"]),
    created_at: z.string(),
    next_attempt_at: z.string().nullable(),
    attempts: z.array(
      z.object({
        id: z.number(),
        started_at: z.string(),
        finished_at: z.string().nullable(),
        outcome: z.enum(["sending", "sent", "failed", "unknown"]),
        failure_code: z.string(),
        response_code: z.number().nullable(),
      }),
    ),
  }),
);
