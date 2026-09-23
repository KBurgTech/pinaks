# Database-backed worker

`uv run python backend/manage.py run_worker` processes work from PostgreSQL. Use
`--once` for a single no-wait cycle; the long-running command polls every second
by default and exits after its current handler when it receives SIGTERM. There is
one code-defined handler registry in `pinaks.apps.workers.registry`.

## Enqueueing and identity

Call `enqueue_work(job_type=..., identity=...)` from the transaction that creates
the business operation. The pair `(job_type, identity)` is unique for the
lifetime of that operation, including success and terminal failure. Use an opaque
operation identifier, not an email address, invoice content, or other personal
data. Repeated enqueue calls return the original record and never reset its
schedule or attempt count. The work row rolls back with the business transaction
if it fails. A caller that cannot share the transaction should enqueue with
`transaction.on_commit` and must tolerate a crash between commit and callback.

## Claiming and handlers

`claim_work` uses PostgreSQL `SELECT ... FOR UPDATE SKIP LOCKED` to let workers
claim distinct eligible rows. Each claim has a random lease token and deadline.
An expired lease can be reclaimed; an expired final attempt becomes terminal.
Completion is accepted only from the current lease token before its deadline.
Handlers must use public module services and make their own business effects
idempotent using the stable work identity. They should commit their business
transaction before reporting success. An interrupted process leaves the lease to
expire; a retry may run the handler again even if its previous side effect
committed. For operations with external side effects, such as SMTP, the provider
handoff may remain ambiguous after a crash and requires a module-specific
idempotency policy.

A raised `Exception` records only the stable `handler_error` code. No exception
message or traceback is persisted or logged by the worker. Retries start at ten
seconds, double after each attempt, and cap at one hour. `max_attempts` ends the
operation in `failed`. An unknown job type records `unknown_job_type` and follows
the same retry limit. `KeyboardInterrupt` and process termination leave the
lease in place for recovery.
