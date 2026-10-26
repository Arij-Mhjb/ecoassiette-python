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
})();
