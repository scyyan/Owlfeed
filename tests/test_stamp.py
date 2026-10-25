import re
import shutil
from pathlib import Path

import pytest

from owlfeed import __main__ as cli
from owlfeed.stamp import _JS_IMPORT, StampError, site_version, stamp_site, unversioned_refs

SITE = Path(__file__).resolve().parents[1] / "site"


def copy_site(tmp_path):
    target = tmp_path / "site"
    shutil.copytree(SITE, target, ignore=shutil.ignore_patterns("data"))
    return target


def test_every_local_asset_and_import_gets_the_same_version(tmp_path):
    site = copy_site(tmp_path)
    version = stamp_site(site)
    assert re.fullmatch(r"[0-9a-f]{12}", version)
    html = (site / "index.html").read_text()
    assert f'href="css/owlfeed.css?v={version}"' in html
    assert f'src="js/app.js?v={version}"' in html
    assert f'src="js/theme-init.js?v={version}"' in html
    assert 'href="favicon.svg"' in html  # only CSS and JS are versioned
    for path in site.glob("js/*.js"):
        for specifier in re.findall(r"""from\s+['"](\.[^'"]+)['"]""", path.read_text()):
            assert specifier.endswith(f".js?v={version}"), (path.name, specifier)


def test_stamping_twice_is_stable_and_changes_follow_content(tmp_path):
    site = copy_site(tmp_path)
    first = stamp_site(site)
    assert stamp_site(site) == first  # existing stamps are ignored when hashing
    html = (site / "index.html").read_text()
    assert html.count("?v=") == html.count(f"?v={first}")
    (site / "js" / "time.js").write_text((site / "js" / "time.js").read_text() + "\n// changed\n")
    second = stamp_site(site)
    assert second != first
    assert f"?v={first}" not in (site / "js" / "render.js").read_text()


def test_the_working_tree_is_never_stamped():
    assert "?v=" not in (SITE / "index.html").read_text()
    assert site_version(SITE)  # hashing alone writes nothing


def test_stamp_command(tmp_path, capsys):
    site = copy_site(tmp_path)
    assert cli.main(["stamp", str(site)]) == 0
    assert "?v=" in (site / "index.html").read_text()
    assert cli.main(["stamp", str(tmp_path / "missing")]) == 2


def test_references_the_stamper_cannot_version_fail_the_stamp(tmp_path):
    for n, html_ref in enumerate((
        '<link rel="stylesheet" href="css/owlfeed.css?x=1">',
        "<script src='js/app.js'></script>",
        '<script src="./js/app.js"></script>',
        '<script SRC="js/app.js"></script>',
        '<script src="js/app.js#main"></script>',
        "<script src=js/app.js></script>",
    )):
        site = copy_site(tmp_path / str(n))
        index = site / "index.html"
        index.write_text(index.read_text().replace("</head>", f"{html_ref}</head>"))
        with pytest.raises(StampError, match="could not be versioned"):
            stamp_site(site)
        assert cli.main(["stamp", str(site)]) == 2
    site = copy_site(tmp_path / "js")
    (site / "js" / "extra.js").write_text("import { x } from './dep.js?x=1';\n")
    with pytest.raises(StampError, match=r"js/extra\.js: \./dep\.js\?x=1"):
        stamp_site(site)


def test_external_and_non_asset_references_are_left_alone(tmp_path):
    site = copy_site(tmp_path)
    index = site / "index.html"
    extra = '<script src="https://cdn.example/lib.js"></script><script src="//cdn.example/x.js"></script>'
    index.write_text(index.read_text().replace("</head>", f"{extra}</head>"))
    (site / "js" / "extra.js").write_text("fetch('data/feed.json'); const s = 'text/css';\n")
    version = stamp_site(site)
    assert extra in index.read_text()
    assert unversioned_refs(index.read_text(), version) == []


def test_only_real_import_keywords_are_rewritten():
    assert [m[3] for m in _JS_IMPORT.finditer("Array.from('./x.js'); reimport('./y.js'); $import('./z.js')")] == []
    found = _JS_IMPORT.finditer("import {a} from './a.js';import('./b.js'); export * from \"./c.js\"")
    assert [m[3] for m in found] == ["./a.js", "./b.js", "./c.js"]


def test_symlinks_are_not_followed(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "elsewhere.js"
    secret.write_text("import './x.js';\n")
    site = copy_site(tmp_path)
    (site / "js" / "linked.js").symlink_to(secret)
    (site / "js" / "linked-dir").symlink_to(outside, target_is_directory=True)
    stamp_site(site)
    assert secret.read_text() == "import './x.js';\n"


def test_stamp_requires_a_path(capsys):
    with pytest.raises(SystemExit):
        cli.main(["stamp"])
    assert "site" in capsys.readouterr().err
