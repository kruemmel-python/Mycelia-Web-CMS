(() => {
  "use strict";

  const SLUG_RE = /^[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?$/;
  const USERNAME_RE = /^[A-Za-z0-9][A-Za-z0-9_.-]{2,31}$/;
  const CURRENCY_RE = /^[A-Z]{3}$/;
  const EMAIL_RE = /^[^\s@]{1,128}@[^\s@]{1,190}\.[^\s@]{2,63}$/;

  const formatBytes = (bytes) => {
    if (bytes >= 1_000_000) return `${(bytes / 1_000_000).toFixed(1).replace(".0", "")} MB`;
    return `${Math.floor(bytes / 1000)} KB`;
  };

  const fieldLabel = (input) => {
    const label = input.closest("label");
    if (label) {
      const clone = label.cloneNode(true);
      clone.querySelectorAll("input,select,textarea,.field-error,.rt-editor").forEach((node) => node.remove());
      const text = clone.textContent.replace(/\s+/g, " ").trim();
      if (text) return text.replace(/[*:]+$/, "").trim();
    }
    return input.getAttribute("aria-label") || input.name || "Dieses Feld";
  };

  const errorNodeFor = (input) => {
    let node = input.previousElementSibling;
    if (!(node instanceof HTMLElement) || !node.classList.contains("field-error")) {
      node = document.createElement("span");
      node.className = "field-error";
      node.setAttribute("role", "alert");
      node.setAttribute("aria-live", "polite");
      input.insertAdjacentElement("beforebegin", node);
    }
    return node;
  };

  const setError = (input, message) => {
    const node = errorNodeFor(input);
    node.textContent = message || "";
    if (message) {
      input.setAttribute("aria-invalid", "true");
      if (input.id) node.id ||= `${input.id}-error`;
      else node.id ||= `field-error-${Math.random().toString(36).slice(2)}`;
      input.setAttribute("aria-describedby", node.id);
    } else {
      input.removeAttribute("aria-invalid");
      if (input.getAttribute("aria-describedby") === node.id) input.removeAttribute("aria-describedby");
    }
    return !message;
  };

  const valueOf = (input) => String(input.value || "");
  const trimmed = (input) => valueOf(input).trim();

  const requiredMessage = (input) => {
    if (input.type === "checkbox") return `Bitte bestätige „${fieldLabel(input)}“.`;
    if (input.type === "file") return `Bitte wähle eine Datei für „${fieldLabel(input)}“ aus.`;
    return `„${fieldLabel(input)}“ darf nicht leer sein.`;
  };

  const validateFileInput = (input) => {
    const files = Array.from(input.files || []);
    if (input.required && !files.length) return setError(input, requiredMessage(input));
    if (!files.length) return setError(input, "");

    const maxCount = Number(input.dataset.maxCount || (input.multiple ? 3 : 1));
    const maxBytes = Number(input.dataset.maxBytes || 0);
    const allowed = (input.accept || "")
      .split(",")
      .map((value) => value.trim().toLowerCase())
      .filter(Boolean);

    if (files.length > maxCount) {
      return setError(input, `Zu viele Dateien ausgewählt. Erlaubt sind maximal ${maxCount}. Bitte entferne ${files.length - maxCount} Datei(en).`);
    }

    if (maxBytes > 0) {
      const oversized = files.find((file) => file.size > maxBytes);
      if (oversized) {
        return setError(input, `„${oversized.name}“ ist zu groß (${formatBytes(oversized.size)}). Maximal erlaubt sind ${formatBytes(maxBytes)}. Bitte verkleinere oder komprimiere die Datei.`);
      }
      const empty = files.find((file) => file.size === 0);
      if (empty) return setError(input, `„${empty.name}“ ist leer. Bitte wähle eine gültige Datei aus.`);
    }

    if (allowed.length) {
      const invalid = files.find((file) => {
        const type = (file.type || "").toLowerCase();
        if (!type) return false; // Der Server prüft Dateibytes verbindlich.
        return !allowed.some((entry) => entry === type || (entry.endsWith("/*") && type.startsWith(entry.slice(0, -1))));
      });
      if (invalid) {
        return setError(input, `„${invalid.name}“ hat ein nicht unterstütztes Format. Erlaubt sind JPEG, PNG oder WebP.`);
      }
    }
    return setError(input, "");
  };

  const exactConfirmation = (input) => {
    if (input.name !== "confirmation") return null;
    const action = input.form?.getAttribute("action") || "";
    if (input.pattern === "RESTORE") return "RESTORE";
    if (action.includes("privacy/delete")) return "DELETE";
    if (action.includes("backup") && action.includes("purge")) return "PURGE BACKUPS";
    if ((input.placeholder || "").toUpperCase() === "PURGE BACKUPS") return "PURGE BACKUPS";
    return null;
  };

  const validateTextLike = (input) => {
    const value = valueOf(input);
    const clean = trimmed(input);

    if (input.required) {
      if (input.type === "checkbox" && !input.checked) return setError(input, requiredMessage(input));
      if (input.type !== "checkbox" && !clean) return setError(input, requiredMessage(input));
    }
    if (!clean && !input.required) return setError(input, "");

    const minLength = Number(input.getAttribute("minlength") || 0);
    const maxLength = Number(input.getAttribute("maxlength") || 0);
    if (minLength > 0 && value.length < minLength) {
      return setError(input, `„${fieldLabel(input)}“ muss mindestens ${minLength} Zeichen lang sein.`);
    }
    if (maxLength > 0 && value.length > maxLength) {
      return setError(input, `„${fieldLabel(input)}“ darf höchstens ${maxLength} Zeichen lang sein. Bitte kürze den Inhalt um ${value.length - maxLength} Zeichen.`);
    }

    if (input.type === "email" || ["email", "contact_email"].includes(input.name)) {
      if (clean.length > 254 || !EMAIL_RE.test(clean)) {
        return setError(input, "Bitte gib eine vollständige gültige E-Mail-Adresse ein, z. B. name@example.de.");
      }
    }

    if (input.name === "username" && input.form?.action?.includes("register")) {
      if (!USERNAME_RE.test(clean)) {
        return setError(input, "Benutzername: 3–32 Zeichen; erlaubt sind Buchstaben, Ziffern, Punkt, Unterstrich und Bindestrich.");
      }
    }

    if (input.name === "slug") {
      if (!SLUG_RE.test(clean)) {
        return setError(input, "Slug: nur Kleinbuchstaben a–z, Ziffern und Bindestriche; kein Leerzeichen, kein Unterstrich, maximal 128 Zeichen.");
      }
    }

    if (input.name === "currency") {
      if (!CURRENCY_RE.test(clean)) {
        return setError(input, "Währung muss aus genau drei Großbuchstaben bestehen, z. B. EUR, USD oder CHF.");
      }
    }

    if (input.name === "website") {
      if (clean && !/^https:\/\/[^\s]{1,1900}$/i.test(clean)) {
        return setError(input, "Die Website muss mit https:// beginnen. Beispiel: https://example.de");
      }
    }

    if (input.name.startsWith("shipping_") && clean.length > 160) {
      return setError(input, `Dieses Adressfeld darf maximal 160 Zeichen enthalten. Bitte kürze es um ${clean.length - 160} Zeichen.`);
    }

    const expected = exactConfirmation(input);
    if (expected && value !== expected) {
      return setError(input, `Bitte gib zur Bestätigung exakt „${expected}“ ein.`);
    }

    if (input.type === "password") {
      const hasPasswordRepeat = input.form?.querySelector('[name="password_repeat"]');
      if ((input.name === "new_password" || (input.name === "password" && hasPasswordRepeat)) && clean && (value.length < 14 || value.length > 256)) {
        return setError(input, "Das Passwort muss zwischen 14 und 256 Zeichen lang sein.");
      }
      const repeatMap = { password_repeat: "password", new_password_repeat: "new_password" };
      const sourceName = repeatMap[input.name];
      if (sourceName) {
        const source = input.form?.elements.namedItem(sourceName);
        if (source instanceof HTMLInputElement && value !== source.value) {
          return setError(input, "Die beiden Passwörter stimmen nicht überein. Bitte wiederhole dasselbe Passwort.");
        }
      }
    }

    if (input.pattern) {
      try {
        const re = new RegExp(`^(?:${input.pattern})$`);
        if (!re.test(value)) return setError(input, `„${fieldLabel(input)}“ hat nicht das erwartete Format.`);
      } catch (_) { /* Ungültiges Pattern soll das Formular nicht unbenutzbar machen. */ }
    }

    return setError(input, "");
  };

  const validateNumber = (input) => {
    const clean = trimmed(input);
    if (!clean) return input.required ? setError(input, requiredMessage(input)) : setError(input, "");
    const number = Number(clean);
    if (!Number.isFinite(number)) return setError(input, `„${fieldLabel(input)}“ muss eine gültige Zahl sein.`);
    if (!Number.isInteger(number)) return setError(input, `„${fieldLabel(input)}“ muss eine ganze Zahl sein.`);

    const min = input.min !== "" ? Number(input.min) : null;
    const max = input.max !== "" ? Number(input.max) : null;
    if (min !== null && number < min) return setError(input, `Der kleinste erlaubte Wert ist ${min}.`);
    if (max !== null && number > max) return setError(input, `Der größte erlaubte Wert ist ${max}.`);
    return setError(input, "");
  };

  const validateSelect = (input) => {
    if (input.required && !input.value) return setError(input, requiredMessage(input));
    return setError(input, "");
  };

  const validateRichText = (source) => {
    const host = source.closest(".rt-field")?.querySelector(".rt-editor");
    const canvas = host?.querySelector(".rt-canvas");
    if (!host || !canvas) return true;
    const text = (canvas.innerText || "").replace(/\u00a0/g, " ").trim();
    const required = host.dataset.rtRequired === "1";
    const maxChars = Number(host.dataset.rtMaxChars || 0);
    const node = errorNodeFor(canvas);

    let message = "";
    if (required && !text) message = "Dieser Inhalt darf nicht leer sein. Bitte gib Text ein.";
    else if (maxChars > 0 && text.length > maxChars) {
      message = `Der Inhalt ist zu lang (${text.length.toLocaleString("de-DE")} Zeichen). Maximal erlaubt sind ${maxChars.toLocaleString("de-DE")} Zeichen. Bitte kürze ihn um ${(text.length - maxChars).toLocaleString("de-DE")} Zeichen.`;
    }
    node.textContent = message;
    if (message) canvas.setAttribute("aria-invalid", "true");
    else canvas.removeAttribute("aria-invalid");
    return !message;
  };

  const validateField = (input) => {
    if (input.disabled || input.type === "hidden" || input.type === "submit" || input.type === "button") return true;
    if (input.type === "file") return validateFileInput(input);
    if (input instanceof HTMLSelectElement) return validateSelect(input);
    if (input instanceof HTMLInputElement && input.type === "number") return validateNumber(input);
    return validateTextLike(input);
  };

  const formFields = (form) => Array.from(form.querySelectorAll("input,select,textarea"))
    .filter((field) => !(field.classList?.contains("rt-source")));

  const validateForm = (form) => {
    const invalid = [];
    formFields(form).forEach((field) => { if (!validateField(field)) invalid.push(field); });
    form.querySelectorAll("textarea.rt-source").forEach((source) => {
      if (!validateRichText(source)) {
        const canvas = source.closest(".rt-field")?.querySelector(".rt-canvas");
        if (canvas) invalid.push(canvas);
      }
    });
    return invalid;
  };

  const focusFirst = (invalid) => {
    if (!invalid.length) return;
    const first = invalid[0];
    first.scrollIntoView({ behavior: "smooth", block: "center" });
    window.setTimeout(() => first.focus?.(), 180);
  };

  const serverMessageTarget = (message, form) => {
    const m = message.toLowerCase();
    const lookup = [
      [/slug/, "slug"], [/währung|currency/, "currency"], [/preis/, "price_cents"], [/bestand|bestellmenge/, "stock"],
      [/benutzername/, "username"], [/e-mail|email/, form.querySelector('[name="contact_email"]') ? "contact_email" : "email"],
      [/anzeigename/, "display_name"], [/website/, "website"], [/passwörter.*nicht überein/, form.querySelector('[name="new_password_repeat"]') ? "new_password_repeat" : "password_repeat"],
      [/passwort/, form.querySelector('[name="current_password"]') ? "current_password" : "password"],
      [/lieferadresse/, "shipping_street"], [/titel|betreff/, form.querySelector('[name="subject"]') ? "subject" : (form.querySelector('[name="title"]') ? "title" : "name")],
      [/bild|avatar|banner|logo/, form.querySelector('[name="banner_image"]') ? "banner_image" : (form.querySelector('[name="image_files"]') ? "image_files" : "avatar_image")],
      [/datei/, "file"], [/bestätigung|delete|restore|purge/, "confirmation"],
    ];
    for (const [pattern, name] of lookup) {
      if (pattern.test(m)) {
        const field = form.querySelector(`[name="${CSS.escape(name)}"]`);
        if (field) return field;
      }
    }
    return null;
  };

  const mirrorServerErrorsToFields = () => {
    const messages = Array.from(document.querySelectorAll(".flash.error[role='alert']"));
    if (!messages.length) return;
    const forms = Array.from(document.querySelectorAll("form"));
    for (const flash of messages) {
      const message = (flash.textContent || "").trim();
      if (!message) continue;
      for (const form of forms) {
        const target = serverMessageTarget(message, form);
        if (target) {
          setError(target, message);
          break;
        }
      }
    }
  };

  const configureKnownFields = () => {
    document.querySelectorAll("form").forEach((form) => { form.noValidate = true; });
    const attrs = {
      slug: { maxlength: "128", pattern: "[a-z0-9](?:[a-z0-9-]{0,126}[a-z0-9])?" },
      title: { maxlength: "180" }, subject: { maxlength: "180" },
      name: { maxlength: "180" }, display_name: { maxlength: "100" },
      email: { maxlength: "254" }, contact_email: { maxlength: "254" },
      username: { minlength: "3", maxlength: "32" },
      password: { maxlength: "256" }, current_password: { maxlength: "512" },
      new_password: { minlength: "14", maxlength: "256" }, new_password_repeat: { minlength: "14", maxlength: "256" }, password_repeat: { minlength: "14", maxlength: "256" },
      website: { maxlength: "1900", inputmode: "url", placeholder: "https://example.de" },
      currency: { minlength: "3", maxlength: "3", pattern: "[A-Z]{3}" },
      price_cents: { min: "0", max: "100000000", step: "1" }, stock: { min: "0", max: "10000000", step: "1" }, quantity: { min: "1", max: "100", step: "1" },
      shipping_name: { maxlength: "160" }, shipping_street: { maxlength: "160" }, shipping_postal_code: { maxlength: "160" }, shipping_city: { maxlength: "160" }, shipping_country: { maxlength: "160" },
    };
    Object.entries(attrs).forEach(([name, values]) => {
      document.querySelectorAll(`[name="${name}"]`).forEach((input) => Object.entries(values).forEach(([k, v]) => {
        if (!input.hasAttribute(k)) input.setAttribute(k, v);
      }));
    });
  };

  document.addEventListener("DOMContentLoaded", () => {
    configureKnownFields();
    mirrorServerErrorsToFields();
  });

  document.addEventListener("input", (event) => {
    const input = event.target;
    if (input instanceof HTMLInputElement || input instanceof HTMLTextAreaElement || input instanceof HTMLSelectElement) {
      if (!input.classList.contains("rt-source")) validateField(input);
      if (["password", "new_password"].includes(input.name)) {
        const repeatName = input.name === "password" ? "password_repeat" : "new_password_repeat";
        const repeat = input.form?.elements.namedItem(repeatName);
        if (repeat instanceof HTMLInputElement && repeat.value) validateField(repeat);
      }
    }
    if (input instanceof HTMLElement && input.classList.contains("rt-canvas")) {
      const source = input.closest(".rt-field")?.querySelector("textarea.rt-source");
      if (source) validateRichText(source);
    }
  });

  document.addEventListener("change", (event) => {
    const input = event.target;
    if (input instanceof HTMLInputElement || input instanceof HTMLSelectElement || input instanceof HTMLTextAreaElement) {
      if (!input.classList.contains("rt-source")) validateField(input);
    }
  });

  document.addEventListener("submit", (event) => {
    if (!(event.target instanceof HTMLFormElement)) return;
    const invalid = validateForm(event.target);
    if (invalid.length) {
      event.preventDefault();
      event.stopImmediatePropagation();
      focusFirst(invalid);
    }
  }, true);
})();
