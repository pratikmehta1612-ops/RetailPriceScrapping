// Runs before the page paints so a saved theme doesn't flash.
(function () {
  try {
    var t = localStorage.getItem("theme");
    if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
  } catch (e) { /* storage unavailable */ }
})();
