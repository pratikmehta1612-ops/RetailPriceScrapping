"use strict";

(function applySavedTheme() {
  try {
    const t = localStorage.getItem("theme");
    if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  } catch { /* storage unavailable */ }
})();

const form = document.getElementById("login");
const error = document.getElementById("error");
const submit = document.getElementById("submit");
const pw = document.getElementById("password");

function showError(message) {
  error.textContent = message;
  error.hidden = !message;
}

function nextPath() {
  const next = new URLSearchParams(location.search).get("next") || "/";
  // Only allow paths on this site.
  return next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

document.getElementById("toggle-pw").addEventListener("click", (e) => {
  const showing = pw.type === "text";
  pw.type = showing ? "password" : "text";
  e.currentTarget.textContent = showing ? "Show" : "Hide";
  e.currentTarget.setAttribute("aria-pressed", String(!showing));
  pw.focus();
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = document.getElementById("username").value.trim();
  const password = pw.value;
  if (!username || !password) {
    showError("Enter your username and password.");
    return;
  }
  showError("");
  submit.disabled = true;
  submit.innerHTML = '<span class="spinner" aria-hidden="true"></span>Signing in';
  try {
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (res.ok) {
      location.replace(nextPath());
      return;
    }
    const data = await res.json().catch(() => ({}));
    showError(data.detail || "Sign-in failed. Try again.");
    pw.select();
  } catch {
    showError("Can't reach the app. Check that it's running, then try again.");
  } finally {
    submit.disabled = false;
    submit.textContent = "Sign in";
  }
});

fetch("/api/login-info")
  .then((r) => r.json())
  .then((info) => { document.getElementById("setup").hidden = info.users_configured; })
  .catch(() => {});
document.getElementById("username").focus();
