import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { assertCompleteTranslations, resources } from "@/i18n";
import {
  ApplicationDialog,
  DataTable,
  DestructiveConfirmation,
  Field,
  PageHeader,
  Status,
} from "@/ui/primitives";

describe("shared application primitives", () => {
  it("gives pages one clear heading and action region", () => {
    render(
      <PageHeader title="Customers" description="Manage customer records">
        <button type="button">Add customer</button>
      </PageHeader>,
    );

    expect(screen.getByRole("heading", { level: 1, name: "Customers" })).toBeInTheDocument();
    expect(screen.getByText("Manage customer records")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add customer" })).toBeInTheDocument();
  });

  it("associates field errors with their control", () => {
    render(
      <Field label="Customer number" error="Already in use" inputId="customer-number">
        <input id="customer-number" />
      </Field>,
    );

    const input = screen.getByRole("textbox", { name: "Customer number" });
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Already in use");
  });

  it("renders an information-dense semantic table and status", () => {
    render(
      <>
        <DataTable caption="Customers">
          <thead>
            <tr>
              <th scope="col">Number</th>
              <th scope="col">Name</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>C-001</td>
              <td>Ada Lovelace</td>
            </tr>
          </tbody>
        </DataTable>
        <Status tone="success">Active</Status>
      </>,
    );

    expect(screen.getByRole("table", { name: "Customers" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Number" })).toBeInTheDocument();
    expect(screen.getByText("Active")).toHaveAttribute("data-tone", "success");
  });

  it("provides a labelled general-purpose dialog", async () => {
    render(
      <ApplicationDialog
        title="Edit customer"
        description="Update the customer record."
        triggerLabel="Edit"
        closeLabel="Close"
      >
        <p>Customer form</p>
      </ApplicationDialog>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit customer" });
    expect(dialog).toHaveAccessibleDescription("Update the customer record.");
    expect(screen.getByText("Customer form")).toBeInTheDocument();
    fireEvent.keyDown(dialog, { key: "Escape" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Edit" })).toHaveFocus();
  });

  it("labels destructive confirmation and restores focus when cancelled", async () => {
    const confirm = vi.fn();
    render(
      <DestructiveConfirmation
        title="Archive customer?"
        description="The customer will no longer be selectable."
        triggerLabel="Archive"
        confirmLabel="Archive customer"
        cancelLabel="Keep customer"
        onConfirm={confirm}
      />,
    );

    const trigger = screen.getByRole("button", { name: "Archive" });
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Archive customer?" });
    expect(dialog).toHaveAccessibleDescription("The customer will no longer be selectable.");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Keep customer" })).toHaveFocus();
    });

    fireEvent.click(screen.getByRole("button", { name: "Keep customer" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
    expect(confirm).not.toHaveBeenCalled();
  });
});

describe("translations", () => {
  it("keeps English and German shell keys complete together", () => {
    expect(Object.keys(resources.de.shell).sort()).toEqual(Object.keys(resources.en.shell).sort());
  });

  it("reports missing semantic keys during startup", () => {
    expect(() =>
      assertCompleteTranslations(
        { customers: "Customers", invoices: "Invoices" },
        { customers: "Kunden" },
      ),
    ).toThrow(/invoices/);
  });
});
