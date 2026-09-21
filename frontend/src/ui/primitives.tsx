import { Dialog } from "@base-ui/react/dialog";
import {
  cloneElement,
  useId,
  useRef,
  type ReactElement,
  type ReactNode,
  type TableHTMLAttributes,
} from "react";

interface PageHeaderProps {
  title: string;
  description?: string;
  children?: ReactNode;
}

export function PageHeader({ title, description, children }: PageHeaderProps) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4 border-b border-neutral-200 pb-4">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description !== undefined && (
          <p className="mt-1 text-sm text-neutral-600">{description}</p>
        )}
      </div>
      {children !== undefined && <div className="flex items-center gap-2">{children}</div>}
    </header>
  );
}

interface FieldControlProps {
  "aria-describedby"?: string;
  "aria-invalid"?: boolean | "false" | "true";
}

interface FieldProps {
  label: string;
  inputId: string;
  error?: string;
  hint?: string;
  children: ReactElement<FieldControlProps>;
}

export function Field({ label, inputId, error, hint, children }: FieldProps) {
  const generatedId = useId();
  const descriptionId = `${generatedId}-description`;
  const descriptions = [
    children.props["aria-describedby"],
    error !== undefined || hint !== undefined ? descriptionId : undefined,
  ]
    .filter((value): value is string => value !== undefined)
    .join(" ");

  return (
    <div className="grid gap-1.5">
      <label className="text-sm font-medium" htmlFor={inputId}>
        {label}
      </label>
      {cloneElement(children, {
        "aria-describedby": descriptions || undefined,
        "aria-invalid": error === undefined ? undefined : true,
      })}
      {(error !== undefined || hint !== undefined) && (
        <p
          className={error === undefined ? "text-sm text-neutral-600" : "text-sm text-red-700"}
          id={descriptionId}
        >
          {error ?? hint}
        </p>
      )}
    </div>
  );
}

interface DataTableProps extends TableHTMLAttributes<HTMLTableElement> {
  caption: string;
  children: ReactNode;
}

export function DataTable({ caption, children, className = "", ...props }: DataTableProps) {
  return (
    <div className="overflow-x-auto rounded-md border border-neutral-200">
      <table className={`w-full border-collapse text-sm ${className}`} {...props}>
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}

type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

const statusClasses: Record<StatusTone, string> = {
  neutral: "bg-neutral-100 text-neutral-800",
  info: "bg-blue-100 text-blue-800",
  success: "bg-emerald-100 text-emerald-800",
  warning: "bg-amber-100 text-amber-900",
  danger: "bg-red-100 text-red-800",
};

interface StatusProps {
  tone?: StatusTone;
  children: ReactNode;
}

export function Status({ tone = "neutral", children }: StatusProps) {
  return (
    <span
      className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${statusClasses[tone]}`}
      data-tone={tone}
    >
      {children}
    </span>
  );
}

interface ApplicationDialogProps {
  title: string;
  description: string;
  triggerLabel: string;
  closeLabel: string;
  children: ReactNode;
}

export function ApplicationDialog({
  title,
  description,
  triggerLabel,
  closeLabel,
  children,
}: ApplicationDialogProps) {
  return (
    <Dialog.Root>
      <Dialog.Trigger className="rounded-md border border-neutral-300 px-3 py-2 text-sm font-medium">
        {triggerLabel}
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 bg-black/40" />
        <Dialog.Viewport className="fixed inset-0 grid place-items-center p-4">
          <Dialog.Popup className="w-full max-w-2xl rounded-lg bg-white p-6 shadow-xl">
            <Dialog.Title className="text-lg font-semibold">{title}</Dialog.Title>
            <Dialog.Description className="mt-2 text-sm text-neutral-600">
              {description}
            </Dialog.Description>
            <div className="mt-5">{children}</div>
            <Dialog.Close className="mt-6 rounded-md border border-neutral-300 px-3 py-2 text-sm font-medium">
              {closeLabel}
            </Dialog.Close>
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

interface DestructiveConfirmationProps {
  title: string;
  description: string;
  triggerLabel: string;
  confirmLabel: string;
  cancelLabel: string;
  onConfirm: () => void;
}

export function DestructiveConfirmation({
  title,
  description,
  triggerLabel,
  confirmLabel,
  cancelLabel,
  onConfirm,
}: DestructiveConfirmationProps) {
  const cancelRef = useRef<HTMLButtonElement>(null);

  return (
    <Dialog.Root>
      <Dialog.Trigger className="rounded-md border border-red-300 px-3 py-2 text-sm font-medium text-red-800">
        {triggerLabel}
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 bg-black/40" />
        <Dialog.Viewport className="fixed inset-0 grid place-items-center p-4">
          <Dialog.Popup
            className="w-full max-w-md rounded-lg bg-white p-6 shadow-xl"
            initialFocus={cancelRef}
          >
            <Dialog.Title className="text-lg font-semibold">{title}</Dialog.Title>
            <Dialog.Description className="mt-2 text-sm text-neutral-600">
              {description}
            </Dialog.Description>
            <div className="mt-6 flex justify-end gap-3">
              <Dialog.Close
                ref={cancelRef}
                className="rounded-md border border-neutral-300 px-3 py-2 text-sm font-medium"
              >
                {cancelLabel}
              </Dialog.Close>
              <Dialog.Close
                className="rounded-md bg-red-700 px-3 py-2 text-sm font-medium text-white"
                onClick={onConfirm}
              >
                {confirmLabel}
              </Dialog.Close>
            </div>
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
