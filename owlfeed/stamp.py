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
# The keyword must stand alone: "Array.from('./x.js')" or "reimport('./x.js')" is not an import.
_JS_IMPORT = re.compile(
    r'''((?<![\w$.])(?:from|import)\s*\(?\s*)(['"])(\.{1,2}/[\w./-]+\.js)(?:\?v=[0-9a-f]+)?\2'''
)
# Any quoted (or unquoted attribute) local .js/.css reference, to catch ones the patterns above missed.
_LOCAL_REF = re.compile(
    r'''(?:(["'`])|=)(?!https?:|//)([^"'`\s<>=]*?\.(?:js|css))([?#][^"'`\s<>]*)?(?(1)\1|(?=[\s>]))''',
    re.IGNORECASE,
)


class StampError(RuntimeError):
    """Some local asset reference could not be versioned; publishing it would mix deploys."""


def _real_files(site: Path, pattern: str) -> list[Path]:
    """Files under site matching pattern, skipping symlinks and anything that resolves outside site."""
    root = site.resolve()
    found = []
    for path in site.glob(pattern):
        if path.is_symlink() or not path.is_file():
            continue
        if not path.resolve().is_relative_to(root):
            continue  # reached through a symlinked directory
        found.append(path)
    return found


def asset_files(site: Path) -> list[Path]:
    return sorted([*_real_files(site, "css/**/*.css"), *_real_files(site, "js/**/*.js")])


def _unstamped(text: str) -> str:
    """The text without any ?v= stamps, so re-stamping is stable."""
    text = _HTML_REF.sub(lambda m: f"{m[1]}{m[2]}{m[3]}", text)
    return _JS_IMPORT.sub(lambda m: f"{m[1]}{m[2]}{m[3]}{m[2]}", text)


def site_version(site: Path) -> str:
    """One short hash over every asset's unstamped content: any change gives every URL a new version."""
    digest = hashlib.sha256()
    index = site / "index.html"
    for path in [index, *asset_files(site)]:
        if path.is_file() and not path.is_symlink():
            digest.update(path.relative_to(site).as_posix().encode())
            digest.update(_unstamped(path.read_text(encoding="utf-8")).encode())
    return digest.hexdigest()[:12]


def unversioned_refs(text: str, version: str) -> list[str]:
    """Local .js/.css references in text that do not end in exactly ?v=<version>."""
    return [m[2] + (m[3] or "") for m in _LOCAL_REF.finditer(text) if m[3] != f"?v={version}"]


def stamp_site(site: Path) -> str:
    """Rewrite index.html and the JS modules in place with ?v=<version>. Returns the version.

    Raises StampError if any local stylesheet or script reference is left unversioned afterwards.
    """
    site = Path(site)
    index = site / "index.html"
    if not index.is_file():
        raise FileNotFoundError(f"{index} not found")
    if index.is_symlink():
        raise StampError(f"{index} is a symlink; refusing to rewrite it")
    version = site_version(site)
    html = index.read_text(encoding="utf-8")
    stamped_html = _HTML_REF.sub(lambda m: f"{m[1]}{m[2]}?v={version}{m[3]}", html)
    index.write_text(stamped_html, encoding="utf-8")
    problems = [f"index.html: {ref}" for ref in unversioned_refs(stamped_html, version)]
    for path in _real_files(site, "js/**/*.js"):
        source = path.read_text(encoding="utf-8")
        stamped = _JS_IMPORT.sub(lambda m: f"{m[1]}{m[2]}{m[3]}?v={version}{m[2]}", source)
        if stamped != source:
            path.write_text(stamped, encoding="utf-8")
        name = path.relative_to(site).as_posix()
        problems += [f"{name}: {ref}" for ref in unversioned_refs(stamped, version)]
    if problems:
        raise StampError(
            "these local CSS/JS references could not be versioned (write them as "
            'src="js/x.js" / href="css/x.css" or import … from "./x.js"): ' + ", ".join(problems)
        )
    return version
