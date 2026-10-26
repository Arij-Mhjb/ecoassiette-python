(function () {
  "use strict";

  document.querySelectorAll(".js-share-link").forEach(function (button) {
    button.addEventListener("click", async function () {
      var url = button.dataset.shareUrl;
      try {
        if (navigator.share) await navigator.share({ title: button.dataset.shareTitle, url: url });
        else {
          await navigator.clipboard.writeText(url);
          var label = button.querySelector("span");
          if (label) {
            var original = label.textContent;
            label.textContent = "Lien copié";
            window.setTimeout(function () { label.textContent = original; }, 1800);
          }
        }
      } catch (error) {
        if (error && error.name !== "AbortError") window.prompt("Copiez ce lien :", url);
      }
    });
  });

  function installerMention(input, popup, apiUrl, select, chips) {
    var results = [], active = 0, controller = null, timer = null;

    function renderChips() {
      if (!select || !chips) return;
      chips.replaceChildren();
      Array.from(select.selectedOptions).forEach(function (option) {
        var chip = document.createElement("button");
        chip.type = "button";
        chip.className = "mention-chip";
        chip.textContent = "@" + option.textContent.trim() + " ×";
        chip.setAttribute("aria-label", "Retirer la mention de " + option.textContent.trim());
        chip.addEventListener("click", function () {
          option.selected = false;
          select.dispatchEvent(new Event("change"));
        });
        chips.appendChild(chip);
      });
    }

    function fermer() {
      popup.hidden = true;
      popup.replaceChildren();
      results = [];
    }

    function mentionCourante() {
      var avant = input.value.slice(0, input.selectionStart);
      var match = avant.match(/(^|\s)@([\w.-]{0,50})$/);
      return match ? { query: match[2], start: input.selectionStart - match[2].length - 1 } : null;
    }

    function choisir(user) {
      var mention = mentionCourante();
      if (!mention) return;
      var end = input.selectionStart;
      input.value = input.value.slice(0, mention.start) + "@" + user.username + " " + input.value.slice(end);
      var caret = mention.start + user.username.length + 2;
      input.focus();
      input.setSelectionRange(caret, caret);
      if (select) {
        var option = Array.from(select.options).find(function (item) { return item.value === String(user.id); });
        if (option) option.selected = true;
        select.dispatchEvent(new Event("change"));
      }
      fermer();
    }

    function afficher(users) {
      results = users;
      active = 0;
      popup.replaceChildren();
      users.forEach(function (user, index) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "mention-suggestion" + (index === active ? " is-active" : "");
        button.setAttribute("role", "option");
        button.setAttribute("aria-selected", index === active ? "true" : "false");
        var pseudo = document.createElement("strong");
        pseudo.textContent = "@" + user.username;
        var nom = document.createElement("span");
        nom.textContent = user.nom;
        button.append(pseudo, nom);
        button.addEventListener("mousedown", function (event) { event.preventDefault(); choisir(user); });
        popup.appendChild(button);
      });
      popup.hidden = users.length === 0;
    }

    function changerSelection(delta) {
      if (!results.length) return;
      active = (active + delta + results.length) % results.length;
      popup.querySelectorAll(".mention-suggestion").forEach(function (node, index) {
        node.classList.toggle("is-active", index === active);
        node.setAttribute("aria-selected", index === active ? "true" : "false");
      });
    }

    input.addEventListener("input", function () {
      window.clearTimeout(timer);
      var mention = mentionCourante();
      if (!mention) { fermer(); return; }
      timer = window.setTimeout(async function () {
        if (controller) controller.abort();
        controller = new AbortController();
        try {
          var response = await fetch(apiUrl + "?q=" + encodeURIComponent(mention.query), {
            headers: { "X-Requested-With": "XMLHttpRequest" }, signal: controller.signal
          });
          if (response.ok) afficher((await response.json()).resultats || []);
        } catch (error) { if (error.name !== "AbortError") fermer(); }
      }, 180);
    });
    input.addEventListener("keydown", function (event) {
      if (popup.hidden) return;
      if (event.key === "ArrowDown") { event.preventDefault(); changerSelection(1); }
      else if (event.key === "ArrowUp") { event.preventDefault(); changerSelection(-1); }
      else if (event.key === "Enter" && results.length) { event.preventDefault(); choisir(results[active]); }
      else if (event.key === "Escape") fermer();
    });
    input.addEventListener("blur", function () { window.setTimeout(fermer, 120); });
    if (select) select.addEventListener("change", renderChips);
    renderChips();
  }

  document.querySelectorAll("[data-mention-url]").forEach(function (container) {
    var select = container.querySelector(".js-mentions-select");
    var chips = container.querySelector(".mention-chips");
    container.querySelectorAll("[data-mention-input]").forEach(function (input) {
      var popup = input.parentElement.querySelector(".mention-suggestions");
      if (popup) installerMention(input, popup, container.dataset.mentionUrl, select, chips);
    });
  });

  var compose = document.querySelector(".community-compose[data-image-ai-url]");
  if (compose) {
    var generateButton = compose.querySelector(".js-generate-image");
    var removeButton = compose.querySelector(".js-remove-ai-image");
    var textInput = compose.querySelector("[name='texte']");
    var fileInput = compose.querySelector("[name='image']");
    var tokenInput = compose.querySelector("[name='image_ia_token']");
    var status = compose.querySelector(".community-ai-status");
    var preview = compose.querySelector(".community-ai-preview");
    var previewImage = preview.querySelector("img");
    var csrf = compose.querySelector("[name='csrfmiddlewaretoken']");

    function retirerImageIA() {
      tokenInput.value = "";
      previewImage.removeAttribute("src");
      preview.hidden = true;
      status.textContent = "";
    }

    removeButton.addEventListener("click", retirerImageIA);
    fileInput.addEventListener("change", function () {
      if (fileInput.files.length) retirerImageIA();
    });
    generateButton.addEventListener("click", async function () {
      var texte = textInput.value.trim();
      if (texte.length < 8) {
        status.textContent = "Écrivez d’abord une description plus précise de votre publication.";
        textInput.focus();
        return;
      }
      generateButton.disabled = true;
      generateButton.setAttribute("aria-busy", "true");
      generateButton.querySelector("span").textContent = "Génération en cours…";
      status.textContent = "Le modèle prépare votre image. Cela peut prendre jusqu’à une minute.";
      var donnees = new FormData();
      donnees.append("texte", texte);
      donnees.append("ancien_token", tokenInput.value);
      donnees.append("csrfmiddlewaretoken", csrf.value);
      try {
        var response = await fetch(compose.dataset.imageAiUrl, {
          method: "POST", body: donnees, headers: { "X-Requested-With": "XMLHttpRequest" }
        });
        var resultat = await response.json();
        if (!response.ok) throw new Error(resultat.erreur || "La génération a échoué.");
        tokenInput.value = resultat.token;
        previewImage.src = resultat.url;
        preview.hidden = false;
        fileInput.value = "";
        status.textContent = "Image créée avec " + resultat.modele + ". Vous pouvez la régénérer ou publier.";
      } catch (error) {
        status.textContent = error.message || "Impossible de générer l’image pour le moment.";
      } finally {
        generateButton.disabled = false;
        generateButton.removeAttribute("aria-busy");
        generateButton.querySelector("span").textContent = "Générer depuis mon texte";
      }
    });
  }
})();
