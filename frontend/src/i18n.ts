import i18n from "i18next";
import { initReactI18next } from "react-i18next";

export const UI_LANGUAGE_STORAGE_KEY = "pinaks.uiLanguage";

export const resources = {
  en: {
    shell: {
      brand: "Pinaks",
      loading: "Loading application…",
      loadError: "The application could not be loaded.",
      signInHeading: "Sign in to Pinaks",
      signIn: "Sign in",
      mainNavigation: "Main navigation",
      customers: "Customers",
      catalog: "Catalog",
      invoices: "Invoices",
      newInvoice: "New invoice",
      settings: "Settings",
      users: "Users",
      switchToGerman: "Deutsch",
      switchToEnglish: "English",
      workspaceHeading: "Workspace",
      workspaceDescription: "Choose an area from the main navigation.",
    },
  },
  de: {
    shell: {
      brand: "Pinaks",
      loading: "Anwendung wird geladen…",
      loadError: "Die Anwendung konnte nicht geladen werden.",
      signInHeading: "Bei Pinaks anmelden",
      signIn: "Anmelden",
      mainNavigation: "Hauptnavigation",
      customers: "Kunden",
      catalog: "Katalog",
      invoices: "Rechnungen",
      newInvoice: "Neue Rechnung",
      settings: "Einstellungen",
      users: "Benutzer",
      switchToGerman: "Deutsch",
      switchToEnglish: "English",
      workspaceHeading: "Arbeitsbereich",
      workspaceDescription: "Wählen Sie einen Bereich in der Hauptnavigation.",
    },
  },
} as const;

export function assertCompleteTranslations(
  reference: Readonly<Record<string, string>>,
  candidate: Readonly<Record<string, string>>,
): void {
  const missingKeys = Object.keys(reference).filter((key) => !(key in candidate));
  if (missingKeys.length > 0) {
    throw new Error(`Missing translation keys: ${missingKeys.join(", ")}`);
  }
}

assertCompleteTranslations(resources.en.shell, resources.de.shell);

function initialLanguage(): "en" | "de" {
  const stored = localStorage.getItem(UI_LANGUAGE_STORAGE_KEY);
  if (stored === "en" || stored === "de") {
    return stored;
  }

  return navigator.language.toLowerCase().startsWith("de") ? "de" : "en";
}

void i18n.use(initReactI18next).init({
  resources,
  lng: initialLanguage(),
  fallbackLng: false,
  defaultNS: "shell",
  interpolation: { escapeValue: false },
  returnNull: false,
});

document.documentElement.lang = i18n.resolvedLanguage ?? "en";

export async function setUiLanguage(language: "en" | "de"): Promise<void> {
  await i18n.changeLanguage(language);
  localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, language);
  document.documentElement.lang = language;
}

export { i18n };
