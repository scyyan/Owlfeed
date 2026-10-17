"""Version the dashboard's CSS and JavaScript URLs so a deploy can never mix old and new files.

GitHub Pages lets browsers cache files for about ten minutes. Without versioned URLs, a reader who
arrives just after a deploy can get the new render.js with a cached old filters.js; if an import
changed, the module graph fails and the page is blank. `stamp` adds `?v=<content hash>` to every
local stylesheet, script and module import, so a new deploy is fetched as a complete new set.

Run it on the copy of site/ that gets published (CI), not on the working tree you edit.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

# href="css/owlfeed.css" / src="js/app.js", with or without an earlier ?v= stamp.
_HTML_REF = re.compile(r'''(\b(?:href|src)=")((?:css|js)/[\w./-]+\.(?:css|js))(?:\?v=[0-9a-f]+)?(")''')
# import … from './filters.js' / import './x.js' / import('./x.js'), relative specifiers only.
_JS_IMPORT = re.compile(r'''(\b(?:from|import)\s*\(?\s*)(['"])(\.{1,2}/[\w./-]+\.js)(?:\?v=[0-9a-f]+)?\2''')


def asset_files(site: Path) -> list[Path]:
    return sorted([*site.glob("css/**/*.css"), *site.glob("js/**/*.js")])


def _unstamped(text: str) -> str:
    """The text without any ?v= stamps, so re-stamping is stable."""
    text = _HTML_REF.sub(lambda m: f"{m[1]}{m[2]}{m[3]}", text)
    return _JS_IMPORT.sub(lambda m: f"{m[1]}{m[2]}{m[3]}{m[2]}", text)


def site_version(site: Path) -> str:
    """One short hash over every asset's unstamped content: any change gives every URL a new version."""
    digest = hashlib.sha256()
    for path in [site / "index.html", *asset_files(site)]:
        if path.exists():
            digest.update(path.relative_to(site).as_posix().encode())
            digest.update(_unstamped(path.read_text(encoding="utf-8")).encode())
    return digest.hexdigest()[:12]


def stamp_site(site: Path) -> str:
    """Rewrite index.html and the JS modules in place with ?v=<version>. Returns the version."""
    site = Path(site)
    index = site / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"{index} not found")
    version = site_version(site)
    html = index.read_text(encoding="utf-8")
    index.write_text(_HTML_REF.sub(lambda m: f"{m[1]}{m[2]}?v={version}{m[3]}", html), encoding="utf-8")
    for path in site.glob("js/**/*.js"):
        source = path.read_text(encoding="utf-8")
        stamped = _JS_IMPORT.sub(lambda m: f"{m[1]}{m[2]}{m[3]}?v={version}{m[2]}", source)
        if stamped != source:
            path.write_text(stamped, encoding="utf-8")
    return version
