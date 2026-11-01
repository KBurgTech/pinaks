import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/api/client";
import { i18n } from "@/i18n";
import { AccountPage, UsersPage } from "./accounts-page";

vi.mock("@/api/client", () => ({ apiClient: { GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() } }));
const get = vi.mocked(apiClient.GET);
const post = vi.mocked(apiClient.POST);
const patch = vi.mocked(apiClient.PATCH);
const user = {
  id: 7,
  username: "member",
  email: "member@example.test",
  role: "read_only" as const,
  is_active: true,
  is_protected: false,
  must_change_password: false,
};

function page(component: React.ReactNode) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {component}
    </QueryClientProvider>,
  );
}

beforeEach(async () => {
  await i18n.changeLanguage("en");
  get.mockResolvedValue({ data: [user], response: new Response(null, { status: 200 }) });
  post.mockResolvedValue({
    data: { completed: true },
    response: new Response(null, { status: 200 }),
  });
  patch.mockResolvedValue({ data: user, response: new Response(null, { status: 200 }) });
});
afterEach(() => vi.clearAllMocks());

describe("user administration", () => {
  it("creates a user with a temporary password and changes access", async () => {
    page(<UsersPage />);
    const row = await screen.findByRole("row", { name: /member@example.test/ });
    fireEvent.change(within(row).getByRole("combobox"), { target: { value: "company_member" } });
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/api/v1/users/{user_id}/", {
        params: { path: { user_id: 7 } },
        body: { role: "company_member" },
      }),
    );
    fireEvent.click(within(row).getByRole("button", { name: "Deactivate" }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/api/v1/users/{user_id}/", {
        params: { path: { user_id: 7 } },
        body: { is_active: false },
      }),
    );
    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "new-user" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "new@example.test" } });
    fireEvent.change(screen.getByLabelText("Temporary password", { exact: true }), {
      target: { value: "a long temporary password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create user" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/users/", {
        body: {
          username: "new-user",
          email: "new@example.test",
          role: "read_only",
          temporary_password: "a long temporary password",
        },
      }),
    );
    expect(screen.getByLabelText("Temporary password", { exact: true })).toHaveValue("");
  });

  it("assigns a temporary password and presents translated errors with focus", async () => {
    await i18n.changeLanguage("de");
    post.mockResolvedValue({
      error: {
        error: {
          code: "protected_administrator",
          message: "Do not expose raw server text",
          fields: {},
        },
      },
      response: new Response(null, { status: 409 }),
    });
    page(<UsersPage />);
    const row = await screen.findByRole("row", { name: /member@example.test/ });
    fireEvent.change(within(row).getByLabelText("Temporäres Passwort für member"), {
      target: { value: "a replacement temporary password" },
    });
    fireEvent.click(within(row).getByRole("button", { name: "Passwort zuweisen" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "Dieses geschützte Administratorkonto kann hier nicht geändert werden.",
    );
    expect(alert).toHaveFocus();
    expect(screen.queryByText("Do not expose raw server text")).not.toBeInTheDocument();
  });

  it("disables access changes for protected administrators", async () => {
    get.mockResolvedValue({
      data: [{ ...user, is_protected: true, role: "admin" }],
      response: new Response(null, { status: 200 }),
    });
    page(<UsersPage />);
    const row = await screen.findByRole("row", { name: /member@example.test/ });
    expect(within(row).getByRole("combobox")).toBeDisabled();
    expect(within(row).getByRole("button", { name: "Deactivate" })).toBeDisabled();
  });
});

describe("personal account", () => {
  function account(hasPassword = false) {
    get.mockResolvedValue({
      data: {
        username: "member",
        has_password: hasPassword,
        must_change_password: false,
        connections: [{ id: 3, provider: "test-provider" }],
        providers: [
          {
            id: "test-provider",
            name: "Authentik",
            connect_url: "/accounts/oidc/test-provider/login/",
          },
        ],
      },
      response: new Response(null, { status: 200 }),
    });
  }

  it("sets a local password, connects explicitly with CSRF, and disconnects", async () => {
    account();
    document.cookie = "csrftoken=csrf-for-account";
    page(<AccountPage />);
    await screen.findByRole("heading", { name: "My account" });
    fireEvent.change(screen.getByLabelText("New password"), {
      target: { value: "a new local password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save password" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/account/password/", {
        body: { current_password: "", new_password: "a new local password" },
      }),
    );
    const connect = screen.getByRole("button", { name: "Connect Authentik" }).closest("form");
    expect(connect).toHaveAttribute("method", "post");
    expect(connect).toHaveAttribute("action", "/accounts/oidc/test-provider/login/");
    expect(connect?.querySelector('[name="process"]')).toHaveValue("connect");
    expect(connect?.querySelector('[name="csrfmiddlewaretoken"]')).toHaveValue("csrf-for-account");
    fireEvent.click(screen.getByRole("button", { name: "Disconnect test-provider" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/account/connections/{connection_id}/disconnect/", {
        params: { path: { connection_id: 3 } },
      }),
    );
  });

  it("requires current password and explains last-login protection in German", async () => {
    await i18n.changeLanguage("de");
    account(true);
    post.mockResolvedValue({
      error: { error: { code: "last_login_method", message: "Private detail", fields: {} } },
      response: new Response(null, { status: 409 }),
    });
    page(<AccountPage />);
    expect(await screen.findByLabelText("Aktuelles Passwort")).toBeRequired();
    fireEvent.click(screen.getByRole("button", { name: "Verbindung test-provider trennen" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Richten Sie vor dem Trennen der letzten Verbindung ein lokales Passwort ein.",
    );
  });
});

it("rejects malformed account data with a localized load error", async () => {
  get.mockResolvedValue({
    data: { username: "incomplete" },
    response: new Response(null, { status: 200 }),
  });
  page(<AccountPage />);
  expect(await screen.findByRole("alert")).toHaveTextContent("Accounts could not be loaded.");
});
