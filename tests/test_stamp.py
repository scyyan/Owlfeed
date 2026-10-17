import re
import shutil
from pathlib import Path

from owlfeed import __main__ as cli
from owlfeed.stamp import site_version, stamp_site

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
