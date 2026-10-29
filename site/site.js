// beaver.syalia.com: language toggle, snippet tabs and copy buttons.
(function () {
  var KEY = "beaver-lang";
  var langButtons = document.querySelectorAll(".lang button");

  function setLang(lang) {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-en]").forEach(function (el) {
      el.textContent = el.getAttribute("data-" + lang);
    });
    langButtons.forEach(function (b) {
      b.classList.toggle("on", b.dataset.l === lang);
    });
  }

  var saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) {}
  var lang = saved || ((navigator.language || "en").toLowerCase().indexOf("es") === 0 ? "es" : "en");
  setLang(lang);
  langButtons.forEach(function (b) {
    b.addEventListener("click", function () {
      lang = b.dataset.l;
      try { localStorage.setItem(KEY, lang); } catch (e) {}
      setLang(lang);
    });
  });

  var tabs = document.querySelectorAll("#tabs button");
  var current = "dict";
  tabs.forEach(function (t) {
    t.addEventListener("click", function () {
      current = t.dataset.t;
      tabs.forEach(function (o) {
        o.classList.toggle("on", o === t);
        o.setAttribute("aria-selected", o === t ? "true" : "false");
      });
      document.querySelectorAll("[data-snippet],[data-out]").forEach(function (el) {
        el.hidden = (el.dataset.snippet || el.dataset.out) !== current;
      });
      document.getElementById("fname").textContent = current + ".py";
      document.getElementById("guide").href = "docs/" + t.dataset.guide;
    });
  });

  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
    var ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
    return Promise.resolve();
  }

  document.querySelectorAll("button.copy").forEach(function (b) {
    b.addEventListener("click", function () {
      var src = b.dataset.copy === "snippet"
        ? document.querySelector('[data-snippet="' + current + '"]')
        : document.getElementById(b.dataset.copy);
      copyText(src.textContent).then(function () {
        b.textContent = lang === "es" ? "Copiado" : "Copied";
        setTimeout(function () { b.textContent = b.getAttribute("data-" + lang); }, 1500);
      });
    });
  });
})();
