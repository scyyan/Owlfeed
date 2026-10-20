// Runs before the page paints so a saved light/dark choice never flashes the wrong theme.
(function () {
  // Scripts run: CSS hides the "Loading…" line only when they don't (the <noscript> note shows instead).
  document.documentElement.dataset.app = 'starting';
  try {
    var theme = JSON.parse(localStorage.getItem('owlfeed:v1:theme'));
    if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
  } catch (e) {
    // No storage access: follow the system setting.
  }
})();
