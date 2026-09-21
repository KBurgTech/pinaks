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
      paymentRequests: "Payment requests",
      reminders: "Reminders",
      timeTracking: "Time tracking",
      company: {
        heading: "Company settings",
        description: "Manage the company details used for future drafts and documents.",
        identity: "Company identity and contact",
        legalName: "Legal name",
        companyIdentifier: "Company identifier",
        addressLine1: "Address line 1",
        addressLine2: "Address line 2",
        postalCode: "Postal code",
        city: "City",
        countryCode: "Country code",
        email: "Email",
        phone: "Phone",
        taxNumber: "Tax number",
        vatIdentifier: "VAT identifier",
        payment: "Payment details",
        accountHolder: "Account holder",
        iban: "IBAN",
        bic: "BIC",
        paymentInstructions: "Payment instructions",
        defaults: "Language and currency defaults",
        currency: "Currency",
        locale: "Locale",
        uiLanguage: "Default UI language",
        documentLanguage: "Default document language",
        numbering: "Invoice numbering",
        numberPrefix: "Number prefix",
        nextNumber: "Next number",
        numberPadding: "Minimum digits",
        numberReset: "Reset sequence",
        annual: "Annually",
        never: "Never",
        features: "Features",
        save: "Save settings",
        saved: "Settings saved.",
        loadError: "Company settings could not be loaded.",
        saveError: "Company settings could not be saved.",
        requiredLegalName: "Enter a legal name.",
        invalidField: "Check this value.",
      },
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
      paymentRequests: "Zahlungsanforderungen",
      reminders: "Mahnungen",
      timeTracking: "Zeiterfassung",
      company: {
        heading: "Unternehmenseinstellungen",
        description: "Verwalten Sie die Firmendaten für künftige Entwürfe und Dokumente.",
        identity: "Unternehmensidentität und Kontakt",
        legalName: "Rechtlicher Name",
        companyIdentifier: "Unternehmenskennung",
        addressLine1: "Adresszeile 1",
        addressLine2: "Adresszeile 2",
        postalCode: "Postleitzahl",
        city: "Ort",
        countryCode: "Ländercode",
        email: "E-Mail",
        phone: "Telefon",
        taxNumber: "Steuernummer",
        vatIdentifier: "USt-IdNr.",
        payment: "Zahlungsdaten",
        accountHolder: "Kontoinhaber",
        iban: "IBAN",
        bic: "BIC",
        paymentInstructions: "Zahlungshinweise",
        defaults: "Sprach- und Währungsvorgaben",
        currency: "Währung",
        locale: "Gebietsschema",
        uiLanguage: "Standardsprache der Oberfläche",
        documentLanguage: "Standardsprache der Dokumente",
        numbering: "Rechnungsnummerierung",
        numberPrefix: "Nummernpräfix",
        nextNumber: "Nächste Nummer",
        numberPadding: "Mindeststellen",
        numberReset: "Nummernfolge zurücksetzen",
        annual: "Jährlich",
        never: "Nie",
        features: "Funktionen",
        save: "Einstellungen speichern",
        saved: "Einstellungen gespeichert.",
        loadError: "Die Unternehmenseinstellungen konnten nicht geladen werden.",
        saveError: "Die Unternehmenseinstellungen konnten nicht gespeichert werden.",
        requiredLegalName: "Geben Sie einen rechtlichen Namen ein.",
        invalidField: "Prüfen Sie diesen Wert.",
      },
      users: "Benutzer",
      switchToGerman: "Deutsch",
      switchToEnglish: "English",
      workspaceHeading: "Arbeitsbereich",
      workspaceDescription: "Wählen Sie einen Bereich in der Hauptnavigation.",
    },
  },
} as const;

function isTranslationRecord(value: unknown): value is Readonly<Record<string, unknown>> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function assertCompleteTranslations(
  reference: Readonly<Record<string, unknown>>,
  candidate: Readonly<Record<string, unknown>>,
  prefix = "",
): void {
  for (const [key, referenceValue] of Object.entries(reference)) {
    const path = prefix === "" ? key : `${prefix}.${key}`;
    if (!(key in candidate)) {
      throw new Error(`Missing translation key: ${path}`);
    }
    const candidateValue = candidate[key];
    if (isTranslationRecord(referenceValue) && isTranslationRecord(candidateValue)) {
      assertCompleteTranslations(referenceValue, candidateValue, path);
    }
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
