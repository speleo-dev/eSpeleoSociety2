// Passkeys on the member portal (R38). Buttons: [data-passkey-login] (optional data-key), [data-passkey-register].
(function () {
  const supported = window.PublicKeyCredential && navigator.credentials;
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";

  const toBytes = (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(s.length / 4) * 4, "=")), (c) => c.charCodeAt(0));
  const toB64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

  async function post(url, body) {
    const r = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf},
                                body: JSON.stringify(body || {}), credentials: "same-origin"});
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || "Akciu sa nepodarilo vykonať.");
    return data;
  }

  function show(el, text) {
    const box = document.getElementById("passkey-message");
    if (box) { box.textContent = text; box.hidden = false; }
  }

  async function login(button) {
    try {
      const o = await post("/portal/passkey/login-options", {key: button.dataset.key || ""});
      o.challenge = toBytes(o.challenge);
      (o.allowCredentials || []).forEach((c) => { c.id = toBytes(c.id); });
      const c = await navigator.credentials.get({publicKey: o});
      const r = await post("/portal/passkey/login", {credential: {
        id: c.id, rawId: toB64(c.rawId), type: c.type,
        response: {clientDataJSON: toB64(c.response.clientDataJSON), authenticatorData: toB64(c.response.authenticatorData),
                   signature: toB64(c.response.signature), userHandle: c.response.userHandle ? toB64(c.response.userHandle) : null}}});
      window.location = r.redirect;
    } catch (e) { show(button, e.name === "NotAllowedError" ? "Prihlásenie bolo zrušené." : e.message); }
  }

  async function register(button) {
    try {
      const o = await post("/portal/passkey/register-options");
      o.challenge = toBytes(o.challenge);
      o.user.id = toBytes(o.user.id);
      (o.excludeCredentials || []).forEach((c) => { c.id = toBytes(c.id); });
      const c = await navigator.credentials.create({publicKey: o});
      await post("/portal/passkey/register", {credential: {
        id: c.id, rawId: toB64(c.rawId), type: c.type,
        response: {clientDataJSON: toB64(c.response.clientDataJSON), attestationObject: toB64(c.response.attestationObject),
                   transports: c.response.getTransports ? c.response.getTransports() : []}}});
      show(button, "Hotovo. Nabudúce sa prihlásite odtlačkom prsta alebo tvárou.");
      button.hidden = true;
    } catch (e) { show(button, e.name === "NotAllowedError" ? "Nastavenie bolo zrušené." : e.name === "InvalidStateError" ? "Toto zariadenie už passkey má." : e.message); }
  }

  if (!supported) return;
  document.querySelectorAll("[data-passkey-login]").forEach((b) => { b.hidden = false; b.addEventListener("click", () => login(b)); });
  document.querySelectorAll("[data-passkey-register]").forEach((b) => { b.hidden = false; b.addEventListener("click", () => register(b)); });
  document.querySelectorAll("[data-passkey-box]").forEach((b) => { b.hidden = false; });
})();
