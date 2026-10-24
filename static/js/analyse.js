/* Analyse IA asynchrone : POST (202) puis interrogation de l'état jusqu'à la fin.
   Le DOM est construit avec textContent (pas d'innerHTML sur les données IA -> pas de XSS). */
(function () {
  const btn = document.getElementById("btn-analyse");
  if (!btn) return;
  const statut = document.getElementById("ia-statut");
  const zone = document.getElementById("ia-resultat");
  const tplAppliquer = document.getElementById("tpl-appliquer");
  const DELAI_MAX_MS = 90000;

  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }

  function afficherStatut(texte, type) {
    statut.className = "ia-statut" + (type ? " ia-" + type : "");
    statut.replaceChildren();
    if (type === "chargement") statut.append(el("span", "spinner"));
    statut.append(el("span", "", texte));
  }

  function rendre(data) {
    const r = data.resultat;
    const box = el("div", "ia-result");
    box.append(el("p", "ia-resume", r.resume));
    const kpis = el("div", "ia-kpis");
    const k1 = el("div", "ia-kpi");
    k1.append(el("span", "small muted", "Score de durabilité"), el("strong", "", r.score_durabilite + "/100"));
    const k2 = el("div", "ia-kpi");
    k2.append(el("span", "small muted", "Objectif recommandé"), el("strong", "", Number(r.objectif_recommande_kg).toLocaleString("fr-FR") + " kg/sem."));
    const form = tplAppliquer.content.firstElementChild.cloneNode(true);
    form.action = data.url_etat + "appliquer/";
    k2.append(form);
    kpis.append(k1, k2);
    box.append(kpis);
    if (r.alternatives && r.alternatives.length) {
      box.append(el("h3", "", "Alternatives végétales pour vous"));
      const ul = el("ul", "alts");
      r.alternatives.forEach(function (a) {
        const li = el("li");
        li.append(el("span", "alt-from", a.aliment), document.createTextNode(" → "), el("strong", "", a.remplacement));
        if (a.idee) { li.append(el("br")); li.append(el("span", "small", a.idee)); }
        ul.append(li);
      });
      box.append(ul);
    }
    box.append(el("h3", "", "Conseils"));
    const ul2 = el("ul", "conseils");
    (r.conseils || []).forEach(function (c) { ul2.append(el("li", "", c)); });
    box.append(ul2);
    const src = data.source === "GEMINI" ? "Gemini (API)" : "Moteur local (repli)";
    box.append(el("p", "small muted", "Source : " + src + " · " + data.duree_ms + " ms"));
    zone.replaceChildren(box);
    zone.hidden = false;
  }

  async function suivre(url, debut) {
    const resp = await fetch(url, { headers: { "Accept": "application/json" } });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const data = await resp.json();
    if (!data.termine) {
      if (Date.now() - debut > DELAI_MAX_MS) throw new Error("délai");
      afficherStatut("Analyse en cours… (" + Math.round((Date.now() - debut) / 1000) + " s)", "chargement");
      await new Promise(function (r) { setTimeout(r, 1000); });
      return suivre(url, debut);
    }
    return data;
  }

  btn.addEventListener("click", async function () {
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    afficherStatut("Envoi de votre profil à l'IA…", "chargement");
    const debut = Date.now();
    try {
      const resp = await fetch(btn.dataset.url, {
        method: "POST",
        headers: { "X-CSRFToken": btn.dataset.csrf, "Accept": "application/json" },
      });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      let data = await resp.json();
      if (!data.termine) data = await suivre(data.url_etat, debut);
      if (data.statut === "ECHEC") {
        afficherStatut(data.erreur || "L'analyse a échoué. Réessayez.", "erreur");
      } else {
        rendre(data);
        const note = data.source === "LOCAL" ? " (service IA indisponible : moteur local utilisé)" : "";
        afficherStatut("Analyse terminée en " + ((Date.now() - debut) / 1000).toLocaleString("fr-FR", { maximumFractionDigits: 1 }) + " s" + note + ".", "ok");
        btn.textContent = "Relancer l'analyse";
      }
    } catch (e) {
      afficherStatut("Impossible de joindre le serveur (" + e.message + "). Vérifiez votre connexion et réessayez.", "erreur");
    } finally {
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
    }
  });
})();
