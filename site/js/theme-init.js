// Runs before the page paints so a saved light/dark choice never flashes the wrong theme.
(function () {
  try {
    var theme = JSON.parse(localStorage.getItem('owlfeed:v1:theme'));
    if (theme === 'light' || theme === 'dark') document.documentElement.dataset.theme = theme;
  } catch (e) {
    // No storage access: follow the system setting.
  }
})();
