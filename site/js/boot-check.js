// A plain script, separate from the app's modules, so it still runs when they fail to load or
// throw while starting (for example a browser holding an older copy of one file after an update).
// If the app hasn't said it started, the endless "Loading…" becomes a message and a Reload button.
(function () {
  var root = document.documentElement;
  // Normally the verdict comes once the app's module has run (its 'load' event, below). This timer
  // is only a backstop for a load that never finishes, so it is generous: a slow connection can take
  // a while to fetch every module, and that is not a failure.
  var BACKSTOP_MS = 60000;
  var shown = false;

  function started() {
    return root.dataset.app === 'ready';
  }

  function fail() {
    if (shown || started()) return;
    shown = true;
    var feed = document.getElementById('feed');
    if (!feed) return;

    var box = document.createElement('div');
    box.className = 'empty';
    var title = document.createElement('p');
    title.className = 'empty-title';
    title.textContent = 'Owlfeed couldn’t start';
    var detail = document.createElement('p');
    detail.className = 'empty-detail';
    detail.textContent =
      'Part of the page didn’t load. This usually happens when the browser keeps an older copy of a file after an update. Reloading fixes it.';
    var button = document.createElement('button');
    button.className = 'btn';
    button.type = 'button';
    button.textContent = 'Reload';
    button.addEventListener('click', function () {
      location.reload();
    });
    box.append(title, detail, button);
    feed.replaceChildren(box);
    feed.setAttribute('aria-busy', 'false');

    var updated = document.getElementById('updated');
    if (updated) updated.textContent = 'Not started';
    var announcer = document.getElementById('announcer');
    if (announcer) announcer.textContent = 'Owlfeed couldn’t start. Reload the page to try again.';
  }

  // One of this site's scripts failing to load or throwing before the app is up means it won't
  // finish starting: say so now rather than wait. (Errors from elsewhere, such as a browser
  // extension, are left to the timer.) Capturing also catches load errors on <script> elements.
  window.addEventListener(
    'error',
    function (event) {
      var target = event.target;
      var ours =
        (target && target.tagName === 'SCRIPT') ||
        (typeof event.filename === 'string' && event.filename.indexOf(location.origin + '/') === 0);
      if (ours && !started()) setTimeout(fail, 300);
    },
    true
  );
  // A module script fires 'load' after it has run (with its imports). If the app is still not up
  // by then, it threw while starting.
  window.addEventListener(
    'load',
    function (event) {
      var target = event.target;
      if (target && target.tagName === 'SCRIPT' && target.type === 'module' && !started()) setTimeout(fail, 300);
    },
    true
  );
  setTimeout(fail, BACKSTOP_MS);
})();
