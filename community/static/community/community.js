(function () {
  "use strict";

  document.querySelectorAll(".js-share-link").forEach(function (button) {
    button.addEventListener("click", async function () {
      var url = button.dataset.shareUrl;
      var title = button.dataset.shareTitle;
      try {
        if (navigator.share) await navigator.share({ title: title, url: url });
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

  var compose = document.querySelector(".community-compose");
  if (!compose) return;
  var input = compose.querySelector("[data-mention-input]");
  var select = compose.querySelector(".js-mentions-select");
  var popup = compose.querySelector(".mention-suggestions");
  var chips = compose.querySelector(".mention-chips");
  if (!input || !select || !popup) return;

  var results = [];
  var active = 0;
  var controller = null;
  var timer = null;

  function selectedValues() {
    return Array.from(select.selectedOptions).map(function (option) { return option.value; });
  }

  function renderChips() {
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

  function closePopup() {
    popup.hidden = true;
    popup.replaceChildren();
    results = [];
  }

  function currentMention() {
    var before = input.value.slice(0, input.selectionStart);
    var match = before.match(/(^|\s)@([\w.-]{1,50})$/);
    return match ? { query: match[2], start: input.selectionStart - match[2].length - 1 } : null;
  }

  function choose(user) {
    var mention = currentMention();
    if (!mention) return;
    var end = input.selectionStart;
    input.value = input.value.slice(0, mention.start) + "@" + user.username + " " + input.value.slice(end);
    var caret = mention.start + user.username.length + 2;
    input.focus();
    input.setSelectionRange(caret, caret);
    var option = Array.from(select.options).find(function (item) { return item.value === String(user.id); });
    if (option) option.selected = true;
    select.dispatchEvent(new Event("change"));
    closePopup();
  }

  function renderResults(users) {
    results = users;
    active = 0;
    popup.replaceChildren();
    users.forEach(function (user, index) {
      var button = document.createElement("button");
      button.type = "button";
      button.className = "mention-suggestion" + (index === active ? " is-active" : "");
      button.setAttribute("role", "option");
      button.setAttribute("aria-selected", index === active ? "true" : "false");
      var title = document.createElement("strong");
      title.textContent = "@" + user.username;
      var name = document.createElement("span");
      name.textContent = user.nom;
      button.append(title, name);
      button.addEventListener("mousedown", function (event) { event.preventDefault(); choose(user); });
      popup.appendChild(button);
    });
    popup.hidden = users.length === 0;
  }

  function updateActive(delta) {
    if (!results.length) return;
    active = (active + delta + results.length) % results.length;
    popup.querySelectorAll(".mention-suggestion").forEach(function (node, index) {
      node.classList.toggle("is-active", index === active);
      node.setAttribute("aria-selected", index === active ? "true" : "false");
    });
  }

  input.addEventListener("input", function () {
    window.clearTimeout(timer);
    var mention = currentMention();
    if (!mention) { closePopup(); return; }
    timer = window.setTimeout(async function () {
      if (controller) controller.abort();
      controller = new AbortController();
      try {
        var response = await fetch(compose.dataset.mentionUrl + "?q=" + encodeURIComponent(mention.query), {
          headers: { "X-Requested-With": "XMLHttpRequest" }, signal: controller.signal
        });
        if (response.ok) renderResults((await response.json()).resultats || []);
      } catch (error) { if (error.name !== "AbortError") closePopup(); }
    }, 180);
  });

  input.addEventListener("keydown", function (event) {
    if (popup.hidden) return;
    if (event.key === "ArrowDown") { event.preventDefault(); updateActive(1); }
    else if (event.key === "ArrowUp") { event.preventDefault(); updateActive(-1); }
    else if (event.key === "Enter" && results.length) { event.preventDefault(); choose(results[active]); }
    else if (event.key === "Escape") closePopup();
  });
  input.addEventListener("blur", function () { window.setTimeout(closePopup, 120); });
  select.addEventListener("change", renderChips);
  renderChips();
})();
