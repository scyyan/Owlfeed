// Runs before the page paints so a saved light/dark choice never flashes the wrong theme.
(function () {
  // Scripts run: CSS hides the "Loading…" line only when they don't (the <noscript> note shows instead).
  document.documentElement.dataset.app = 'starting';
  // Inside another site's frame the page hides itself (CSS), so it can't be used for clickjacking.
  // GitHub Pages can't send the frame-ancestors header, and a CSP meta tag can't set it.
  var framed;
  try {
    framed = window.top !== window.self;
  } catch (e) {
    framed = true; // a cross-origin parent: reading top threw
  }
  if (framed) document.documentElement.dataset.framed = 'true';
  try {
    var theme = JSON.parse(localStorage.getItem('owlfeed:v1:theme'));
    if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
  } catch (e) {
    // No storage access: follow the system setting.
  }
})();
