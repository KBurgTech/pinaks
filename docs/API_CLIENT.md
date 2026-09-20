# API schema and TypeScript client

The Django REST Framework API under `/api/v1/` is the source of truth. Its
generated OpenAPI document is committed at `backend/schema/openapi.json`, and
the generated TypeScript contract is committed at
`frontend/src/api/generated/schema.ts`.

After changing an API request or response, regenerate both artifacts from the
repository root:

```bash
make api-client
```

Never edit either generated file by hand. `make api-client-check` fails when
the Django schema or TypeScript contract has drifted, and `make check` includes
that guard.

## Dependency justification

- `openapi-typescript` is a development-only generator. It validates the local
  OpenAPI document and emits runtime-free TypeScript types without requiring a
  Java service or a running API server.
- `openapi-fetch` is the small runtime wrapper around the browser Fetch API.
  It binds request paths and response bodies to the generated contract, so the
  frontend does not maintain handwritten transport types. It uses same-origin
  credentials and does not introduce token storage or a second API.
