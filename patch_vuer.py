"""Build-time patches to the installed vuer package (run from the Dockerfile).

1. params-proto compatibility: vuer 0.0.60 imports `Flag`, which
   params-proto 3.x removed.
2. The 360-degree panorama layer: copies vuer_patches/*.js into vuer's
   client_build/assets/ (the one directory every vuer instance serves)
   and injects the <script> tags into client_build/index.html. The page
   then renders any equirectangular WebRTC stream on an inside-out
   sphere; right-controller B (or the 'b' key) toggles it against the
   camera plane. Camera-agnostic: the stream URL comes from the page URL
   (?pano=<offer-url>, default https://<page-host>:60010/offer -- e.g.
   theta-webrtc from the iosb_ricohtheta driver). No stream = the layer
   stays idle and keeps retrying quietly.
"""
import pathlib
import shutil

import vuer

vuer_dir = pathlib.Path(vuer.__file__).parent

# --- 1. params-proto Flag shim ------------------------------------------
server = vuer_dir / "server.py"
server.write_text(server.read_text().replace(
    'from params_proto import Flag, PrefixProto, Proto',
    'from params_proto import PrefixProto, Proto\nFlag = bool'
))

# --- 2. panorama layer ---------------------------------------------------
here = pathlib.Path(__file__).parent
assets = vuer_dir / "client_build" / "assets"
for name in ("pano_boot.js", "pano_sphere.js"):
    shutil.copy(here / "vuer_patches" / name, assets / name)

index = vuer_dir / "client_build" / "index.html"
html = index.read_text()
if "/assets/pano_boot" not in html:
    inject = ('        <script src="/assets/pano_boot.js"></script>\n'
              '        <script type="module" src="/assets/pano_sphere.js" async>'
              '</script>\n        <title>')
    assert '<title>' in html, "no <title> anchor in vuer index.html"
    html = html.replace('        <title>', inject, 1)
    index.write_text(html)

print(f"vuer patched: {vuer_dir}")
