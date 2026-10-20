import re
import struct
from pathlib import Path

SITE = Path(__file__).resolve().parents[1] / "site"


def test_home_screen_icon_is_linked_and_ios_ready():
    html = (SITE / "index.html").read_text()
    href = re.search(r'<link rel="apple-touch-icon" href="([^"]+)"', html)
    assert href, "index.html must link an apple-touch-icon"
    assert 'name="apple-mobile-web-app-title" content="Owlfeed"' in html
    data = (SITE / href[1]).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"  # iOS ignores SVG touch icons
    width, height, _depth, color_type = struct.unpack(">IIBB", data[16:26])
    assert (width, height) == (180, 180)
    assert color_type in (0, 2)  # no alpha: iOS fills transparency with black
