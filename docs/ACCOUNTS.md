# Accounts and OIDC

Pinaks keeps Django users, roles and activation authoritative. Every login creates
an ordinary server-side session. React never handles OAuth tokens. A configured
OIDC provider supplies authorization-code login with PKCE through django-allauth.

## Deployment configuration

Set `OIDC_ISSUER` to the exact HTTPS issuer, `OIDC_CLIENT_ID`, and
`OIDC_CLIENT_SECRET` through deployment secrets. `OIDC_NAME` optionally changes the
provider display name (default: Authentik). Without these values OIDC is disabled;
partial or unsafe configuration fails startup. Do not create database SocialApp
records or place provider secrets in ordinary company configuration.

The provider ID is `oidc-` plus the SHA-256 hex digest of the exact issuer URL.
Register the callback at
`https://<pinaks-host>/accounts/oidc/<provider-id>/login/callback/`.
The issuer must publish standard discovery metadata and return an ID token with a
stable `sub`, correct issuer/audience/expiry and, for automatic provisioning, an
email address. Keep the issuer spelling stable. Changing it deliberately creates
a new identity namespace; it never reuses old subject associations.

Configure Authentik application access/group policies to admit only intended
users. Pinaks trusts a successful login from that configured application as
admitted; groups never assign application privileges. Admission denied by the
provider leaves no user or authenticated session. Real-provider admission and
redirect registration need a deployment smoke test; no live credentials are
needed by the automated fake-provider integration tests.

New admitted identities create Read-Only users with no local password. Returning
identities preserve local roles and activation, even if provider email or groups
change. Matching an existing local email never links identities: sign in locally
and explicitly connect from **My account**. Identity uniqueness is enforced by
allauth's database constraint on provider plus subject. Tokens and unnecessary
profile/group claims are discarded, including during incomplete signup.

## User and account workflows

Admins use `/app/users/` to create users, change roles/activation, and assign
validated temporary passwords. The user must replace the temporary password
before accessing business APIs, the admin, or other application screens. Existing
sessions become invalid when their password hash changes. The password change
keeps the current session and invalidates other sessions. Passwords are submitted
over the same-origin CSRF-protected API, never returned in responses or audit data.

All users can use `/app/account/` to set/change a local password and explicitly
connect/disconnect identities. Setting an initial local password uses the existing
authenticated session; subsequent changes require the current local password.
Connecting locks and reloads the canonical user after the provider exchange so
in-flight local role, activation, and password changes cannot be overwritten.
Removing the last external identity requires a usable local password. Disconnects
serialize against password and other disconnect operations by locking the local
user. The native allauth connections page redirects here; its mutation surface is
closed so it cannot bypass the application service.

Bootstrap an independent protected local administrator with `bootstrap_admin`
before enabling external login. It cannot be demoted, deactivated, deleted, or
assigned a temporary password through user management. It changes its own local
password through the account workflow. Access changes serialize administrator
rows and preserve at least one active administrator. Only the bootstrap admin
receives Django staff/superuser privileges; an application Admin role does not
implicitly grant Django admin access.

Audit events record local/oidc authentication outcomes, external provisioning,
connection changes, account creation, role/activation changes and password changes.
They contain user identifiers and stable action codes, without provider claims,
credentials, or raw provider failure messages.

## Dependencies and verification

The `socialaccount` extra of the existing django-allauth dependency supplies
PyJWT, cryptography, and OAuthlib for standards-based OIDC token validation and
OAuth flows. This avoids a custom authentication implementation or a second API.

Run the account, account-management, OIDC, OIDC-configuration, audit and bilingual
frontend account suites, then `make check`. Before deployment, bootstrap the local
administrator and verify local recovery login, admitted/rejected real-provider
users, exact callback registration, CSRF protection, Read-Only provisioning,
explicit connection, and local deactivation blocking a returning OIDC identity.
