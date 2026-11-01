import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { accountDetailsSchema, managedUsersSchema } from "@/accounts/schemas";
import { apiClient } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { DataTable, Field, PageHeader } from "@/ui/primitives";

type ManagedUser = components["schemas"]["ManagedUser"];
type CreateUser = components["schemas"]["CreateUserRequest"];
type LocalPassword = components["schemas"]["LocalPasswordRequest"];
type UserAccess = components["schemas"]["PatchedUserAccessRequest"];
const inputClass =
  "rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50";
const buttonClass =
  "rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm font-medium hover:bg-neutral-100 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50";
const roles = ["read_only", "company_member", "admin"] as const;

function errorCode(value: unknown): string {
  if (typeof value === "object" && value !== null && "error" in value) {
    const error = value.error;
    if (
      typeof error === "object" &&
      error !== null &&
      "code" in error &&
      typeof error.code === "string"
    ) {
      return error.code;
    }
  }
  return "error";
}

function Notice({ code }: { code: string }) {
  const { t } = useTranslation("shell");
  const ref = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (code !== "saved") ref.current?.focus();
  }, [code]);
  const key =
    code === "saved" ||
    code === "protected_administrator" ||
    code === "last_administrator" ||
    code === "last_login_method"
      ? code
      : "error";
  return (
    <p ref={ref} role={code === "saved" ? "status" : "alert"} tabIndex={-1}>
      {t(`accounts.${key}`)}
    </p>
  );
}

function TemporaryPassword({
  user,
  report,
}: {
  user: ManagedUser;
  report: (code: string) => void;
}) {
  const { t } = useTranslation("shell");
  const form = useForm<{ temporary_password: string }>({
    defaultValues: { temporary_password: "" },
  });
  const mutation = useMutation({
    mutationFn: async (body: { temporary_password: string }) => {
      const result = await apiClient.POST("/api/v1/users/{user_id}/temporary-password/", {
        params: { path: { user_id: user.id } },
        body,
      });
      if (!result.response.ok) throw new Error(errorCode(result.error));
    },
    onSuccess: () => {
      form.reset();
      report("saved");
    },
    onError: (error) => report(error.message),
  });
  return (
    <form
      onSubmit={(event) => void form.handleSubmit((data) => mutation.mutate(data))(event)}
      className="flex flex-wrap gap-2"
    >
      <Field
        label={t("accounts.passwordFor", { username: user.username })}
        inputId={`temporary-${user.id}`}
      >
        <input
          className={inputClass}
          id={`temporary-${user.id}`}
          type="password"
          autoComplete="new-password"
          minLength={12}
          required
          disabled={user.is_protected}
          {...form.register("temporary_password")}
        />
      </Field>
      <button
        className={buttonClass}
        type="submit"
        disabled={user.is_protected || mutation.isPending}
      >
        {t("accounts.assignPassword")}
      </button>
    </form>
  );
}

export function UsersPage() {
  const { t } = useTranslation("shell");
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState("");
  const users = useQuery({
    queryKey: ["managed-users"],
    queryFn: async (): Promise<readonly ManagedUser[]> => {
      const result = await apiClient.GET("/api/v1/users/");
      if (result.data === undefined) throw new Error("load");
      return managedUsersSchema.parse(result.data);
    },
  });
  const form = useForm<CreateUser>({
    defaultValues: { username: "", email: "", role: "read_only", temporary_password: "" },
  });
  const create = useMutation({
    mutationFn: async (body: CreateUser) => {
      const result = await apiClient.POST("/api/v1/users/", { body });
      if (!result.response.ok) throw new Error(errorCode(result.error));
    },
    onSuccess: () => {
      form.reset();
      setNotice("saved");
      void queryClient.invalidateQueries({ queryKey: ["managed-users"] });
    },
    onError: (error) => setNotice(error.message),
  });
  const access = useMutation({
    mutationFn: async ({ id, body }: { id: number; body: UserAccess }) => {
      const result = await apiClient.PATCH("/api/v1/users/{user_id}/", {
        params: { path: { user_id: id } },
        body,
      });
      if (!result.response.ok) throw new Error(errorCode(result.error));
    },
    onSuccess: () => {
      setNotice("saved");
      void queryClient.invalidateQueries({ queryKey: ["managed-users"] });
    },
    onError: (error) => setNotice(error.message),
  });
  return (
    <>
      <PageHeader title={t("accounts.usersHeading")} />
      {notice && <Notice key={notice} code={notice} />}
      {users.isPending ? (
        <p>{t("accounts.loading")}</p>
      ) : users.isError ? (
        <p role="alert">{t("accounts.loadError")}</p>
      ) : (
        <DataTable
          className="[&_th]:p-3 [&_th]:text-start [&_td]:p-3"
          caption={t("accounts.usersHeading")}
        >
          <thead>
            <tr>
              <th>{t("accounts.username")}</th>
              <th>{t("accounts.email")}</th>
              <th>{t("accounts.role")}</th>
              <th>{t("accounts.temporaryPassword")}</th>
            </tr>
          </thead>
          <tbody>
            {users.data.map((user) => (
              <tr key={user.id}>
                <td>{user.username}</td>
                <td>{user.email}</td>
                <td>
                  <select
                    className={inputClass}
                    aria-label={`${t("accounts.role")} ${user.username}`}
                    value={user.role}
                    disabled={user.is_protected || access.isPending}
                    onChange={(event) => {
                      const role = roles.find((value) => value === event.target.value);
                      if (role) access.mutate({ id: user.id, body: { role } });
                    }}
                  >
                    {roles.map((role) => (
                      <option key={role} value={role}>
                        {t(`accounts.roles.${role}`)}
                      </option>
                    ))}
                  </select>
                  <button
                    className={buttonClass}
                    type="button"
                    disabled={user.is_protected || access.isPending}
                    onClick={() =>
                      access.mutate({ id: user.id, body: { is_active: !user.is_active } })
                    }
                  >
                    {t(user.is_active ? "accounts.deactivate" : "accounts.activate")}
                  </button>
                </td>
                <td>
                  <TemporaryPassword user={user} report={setNotice} />
                </td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
      <form
        className="mt-8 grid max-w-lg gap-4"
        onSubmit={(event) => void form.handleSubmit((body) => create.mutate(body))(event)}
      >
        <Field label={t("accounts.username")} inputId="new-username">
          <input
            className={inputClass}
            id="new-username"
            autoComplete="off"
            required
            maxLength={150}
            {...form.register("username")}
          />
        </Field>
        <Field label={t("accounts.email")} inputId="new-email">
          <input
            className={inputClass}
            id="new-email"
            type="email"
            autoComplete="off"
            required
            {...form.register("email")}
          />
        </Field>
        <Field label={t("accounts.role")} inputId="new-role">
          <select className={inputClass} id="new-role" {...form.register("role")}>
            {roles.map((role) => (
              <option key={role} value={role}>
                {t(`accounts.roles.${role}`)}
              </option>
            ))}
          </select>
        </Field>
        <Field label={t("accounts.temporaryPassword")} inputId="new-password">
          <input
            className={inputClass}
            id="new-password"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            {...form.register("temporary_password")}
          />
        </Field>
        <button className={buttonClass} type="submit" disabled={create.isPending}>
          {t("accounts.create")}
        </button>
      </form>
    </>
  );
}

function csrfToken(): string {
  const value = document.cookie
    .split(";")
    .map((cookie) => cookie.trim())
    .find((cookie) => cookie.startsWith("csrftoken="));
  return value ? decodeURIComponent(value.slice("csrftoken=".length)) : "";
}

export function AccountPage() {
  const { t } = useTranslation("shell");
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState("");
  const account = useQuery({
    queryKey: ["personal-account"],
    queryFn: async (): Promise<components["schemas"]["AccountDetails"]> => {
      const result = await apiClient.GET("/api/v1/account/");
      if (result.data === undefined) throw new Error("load");
      return accountDetailsSchema.parse(result.data);
    },
  });
  const form = useForm<LocalPassword>({
    defaultValues: { current_password: "", new_password: "" },
  });
  const password = useMutation({
    mutationFn: async (body: LocalPassword) => {
      const result = await apiClient.POST("/api/v1/account/password/", { body });
      if (!result.response.ok) throw new Error(errorCode(result.error));
    },
    onSuccess: () => {
      form.reset();
      setNotice("saved");
      void queryClient.invalidateQueries({ queryKey: ["personal-account"] });
    },
    onError: (error) => setNotice(error.message),
  });
  const disconnect = useMutation({
    mutationFn: async (id: number) => {
      const result = await apiClient.POST(
        "/api/v1/account/connections/{connection_id}/disconnect/",
        { params: { path: { connection_id: id } } },
      );
      if (!result.response.ok) throw new Error(errorCode(result.error));
    },
    onSuccess: () => {
      setNotice("saved");
      void queryClient.invalidateQueries({ queryKey: ["personal-account"] });
    },
    onError: (error) => setNotice(error.message),
  });
  if (account.isPending) return <p>{t("accounts.loading")}</p>;
  if (account.isError) return <p role="alert">{t("accounts.loadError")}</p>;
  return (
    <>
      <PageHeader title={t("accounts.heading")} />
      {account.data.must_change_password && <p role="alert">{t("accounts.passwordRequired")}</p>}
      {notice && <Notice key={notice} code={notice} />}
      <form
        className="grid max-w-lg gap-4"
        onSubmit={(event) => void form.handleSubmit((data) => password.mutate(data))(event)}
      >
        {account.data.has_password && (
          <Field label={t("accounts.currentPassword")} inputId="current-password">
            <input
              className={inputClass}
              id="current-password"
              type="password"
              autoComplete="current-password"
              required
              {...form.register("current_password")}
            />
          </Field>
        )}
        <Field label={t("accounts.newPassword")} inputId="local-password">
          <input
            className={inputClass}
            id="local-password"
            type="password"
            autoComplete="new-password"
            required
            minLength={12}
            {...form.register("new_password")}
          />
        </Field>
        <button className={buttonClass} type="submit" disabled={password.isPending}>
          {t("accounts.savePassword")}
        </button>
      </form>
      {!account.data.must_change_password && <a href="/app/">{t("accounts.continue")}</a>}
      {!account.data.must_change_password && (
        <section className="mt-8 grid gap-4" aria-label={t("accounts.connections")}>
          <h2 className="text-xl font-semibold">{t("accounts.connections")}</h2>
          {account.data.connections.length === 0 && <p>{t("accounts.emptyConnections")}</p>}
          {account.data.connections.map((connection) => (
            <div key={connection.id}>
              <button
                className={buttonClass}
                type="button"
                disabled={disconnect.isPending}
                onClick={() => disconnect.mutate(connection.id)}
              >
                {t("accounts.disconnect", { provider: connection.provider })}
              </button>
            </div>
          ))}
          {account.data.providers.map((provider) => (
            <form key={provider.id} method="post" action={provider.connect_url}>
              <input type="hidden" name="csrfmiddlewaretoken" value={csrfToken()} />
              <input type="hidden" name="process" value="connect" />
              <button className={buttonClass} type="submit">
                {t("accounts.connect", { provider: provider.name })}
              </button>
            </form>
          ))}
        </section>
      )}
      <a href="/accounts/logout/">{t("accounts.signOut")}</a>
    </>
  );
}
