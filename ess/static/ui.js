(() => {
  // Busy state for POST forms: prevents double submits and shows "Ukladám…".
  const RESTORE_AFTER_MS = 8000;  // safety net when the page stays (download, network error)

  function restore(form) {
    form.dataset.uiBusy = "false";
    form.querySelectorAll("[data-ui-submit-field]").forEach((field) => field.remove());
    form.querySelectorAll("[data-ui-was-disabled]").forEach((control) => {
      control.disabled = control.dataset.uiWasDisabled === "true";
      delete control.dataset.uiWasDisabled;
    });
    form.querySelectorAll('[data-ui-status="true"]').forEach((button) => {
      button.querySelectorAll("[data-ui-status-text]").forEach((status) => status.remove());
      delete button.dataset.uiStatus;
    });
  }

  document.addEventListener("submit", (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || form.method.toLowerCase() !== "post") return;
    // Cancelled by an inline onsubmit="return confirm(...)" or by validation code: leave the form as it is.
    if (event.defaultPrevented) return;
    if (form.dataset.uiBusy === "true") {
      event.preventDefault();
      return;
    }
    // A file download or a new tab keeps this page: do not lock the form.
    if (form.hasAttribute("data-download") || form.target === "_blank") return;

    const submitter = event.submitter;
    if ((submitter instanceof HTMLButtonElement || submitter instanceof HTMLInputElement) && submitter.name) {
      // A disabled submitter is not sent with the form, so its name/value goes in a hidden field.
      const field = document.createElement("input");
      field.type = "hidden";
      field.name = submitter.name;
      field.value = submitter.value;
      field.dataset.uiSubmitField = "true";
      form.append(field);
    }

    form.dataset.uiBusy = "true";
    form.querySelectorAll('button[type="submit"], button:not([type]), input[type="submit"], input[type="image"]')
      .forEach((control) => {
        control.dataset.uiWasDisabled = String(control.disabled);
        control.disabled = true;
      });

    if (submitter instanceof HTMLButtonElement) {
      const status = document.createElement("span");
      status.className = "ms-2";
      status.dataset.uiStatusText = "true";
      status.textContent = "Ukladám…";
      submitter.append(status);
      submitter.dataset.uiStatus = "true";
    }
    window.setTimeout(() => { if (form.isConnected && form.dataset.uiBusy === "true") restore(form); }, RESTORE_AFTER_MS);
  });

  // Back/forward cache: the page comes back with locked forms.
  window.addEventListener("pageshow", () => {
    document.querySelectorAll('form[data-ui-busy="true"]').forEach(restore);
  });

  document.querySelectorAll(".alert-success, .flash.ok, .flash.success").forEach((alert) => {
    window.setTimeout(() => {
      alert.classList.add("ui-fade-out");
      window.setTimeout(() => alert.remove(), 250);
    }, 4000);
  });

  document.addEventListener("keydown", (event) => {
    if (event.key !== "/" || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const target = event.target;
    if (target instanceof HTMLElement && (
      target.isContentEditable || target.matches("input, textarea, select, button")
    )) return;
    const search = document.querySelector("#member-search");
    if (search instanceof HTMLInputElement) {
      event.preventDefault();
      search.focus();
    }
  });
})();
