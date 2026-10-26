/* Menu mobile accessible (aria-expanded) + fermeture avec Échap. */
(function () {
  const toggle = document.querySelector(".nav-toggle");
  const nav = document.getElementById("menu-principal");
  if (!toggle || !nav) return;
  function set(open) {
    toggle.setAttribute("aria-expanded", String(open));
    toggle.querySelector(".sr-only").textContent = open ? "Fermer le menu" : "Ouvrir le menu";
    nav.classList.toggle("open", open);
  }
  toggle.addEventListener("click", function () { set(toggle.getAttribute("aria-expanded") !== "true"); });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && nav.classList.contains("open")) { set(false); toggle.focus(); }
  });
})();

/* Boutons : indicateur de chargement à l'envoi d'un formulaire + anti double-clic. */
(function () {
  document.addEventListener("submit", function (e) {
    const form = e.target;
    setTimeout(function () {
      if (e.defaultPrevented || form.hasAttribute("data-sans-chargement")) return;
      const btn = e.submitter || form.querySelector('button[type="submit"], button:not([type])');
      if (!btn || !btn.classList.contains("btn")) return;
      btn.classList.add("is-loading");
      btn.setAttribute("aria-busy", "true");
      // si l'utilisateur revient avec « Précédent », on remet le bouton à l'état normal
      window.addEventListener("pageshow", function () {
        btn.classList.remove("is-loading"); btn.removeAttribute("aria-busy");
      }, { once: true });
    }, 0);
  });
})();

/* Notifications : fermeture au clic, disparition automatique après 7 s (sauf erreurs, survol ou focus). */
(function () {
  document.querySelectorAll(".toasts .message").forEach(function (m) {
    function fermer() { m.classList.add("sortie"); setTimeout(function () { m.remove(); }, 260); }
    m.querySelector(".message-fermer").addEventListener("click", fermer);
    if (m.classList.contains("message-error")) return;
    let t = setTimeout(fermer, 7000);
    m.addEventListener("mouseenter", function () { clearTimeout(t); });
    m.addEventListener("focusin", function () { clearTimeout(t); });
  });
})();

/* Menu du compte : fermeture au clic extérieur et avec Échap. */
(function () {
  const menu = document.querySelector(".user-menu");
  if (!menu) return;
  document.addEventListener("click", function (e) { if (menu.open && !menu.contains(e.target)) menu.open = false; });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && menu.open) { menu.open = false; menu.querySelector("summary").focus(); }
  });
})();

/* Groupes de navigation : un seul ouvert, fermeture extérieure et avec Échap. */
(function () {
  const groupes = Array.from(document.querySelectorAll(".nav-group"));
  if (!groupes.length) return;
  groupes.forEach(function (groupe) {
    groupe.addEventListener("toggle", function () {
      if (groupe.open) groupes.forEach(function (autre) { if (autre !== groupe) autre.open = false; });
    });
  });
  document.addEventListener("click", function (e) {
    groupes.forEach(function (groupe) { if (groupe.open && !groupe.contains(e.target)) groupe.open = false; });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    const ouvert = groupes.find(function (groupe) { return groupe.open; });
    if (ouvert) { ouvert.open = false; ouvert.querySelector("summary").focus(); }
  });
})();

/* Application installable (PWA) : service worker + bouton « Installer l'application ». */
(function () {
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () { navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(function () {}); });
  }
  let invite = null;
  const boutons = document.querySelectorAll("[data-installer]");
  window.addEventListener("beforeinstallprompt", function (e) {
    e.preventDefault(); invite = e;
    boutons.forEach(function (b) { b.hidden = false; });
  });
  boutons.forEach(function (b) {
    b.addEventListener("click", async function () {
      if (!invite) return;
      invite.prompt();
      await invite.userChoice;
      invite = null;
      boutons.forEach(function (x) { x.hidden = true; });
    });
  });
  window.addEventListener("appinstalled", function () { boutons.forEach(function (x) { x.hidden = true; }); });
})();

/* Thème clair / sombre : bouton lune-soleil, choix mémorisé (sinon réglage du système). */
(function () {
  const b = document.querySelector(".theme-toggle");
  if (!b) return;
  const racine = document.documentElement;
  function maj() {
    const sombre = racine.getAttribute("data-theme") === "dark";
    b.setAttribute("aria-pressed", String(sombre));
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", sombre ? "#0c1411" : "#0b3b2c");
  }
  b.addEventListener("click", function () {
    const sombre = racine.getAttribute("data-theme") !== "dark";
    racine.setAttribute("data-theme", sombre ? "dark" : "light");
    try { localStorage.setItem("theme", sombre ? "dark" : "light"); } catch (e) {}
    maj();
  });
  maj();
})();
