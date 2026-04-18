#!/usr/bin/env python3
"""
LUNAR EXPLORATION — All-in-one launcher.

A single 3D web app with two views: OPTICAL (LROC imagery) and THERMAL
(physics-based surface temperature model). Toggle between them, toggle
the sun on/off, and inspect anywhere with a hover probe.

    python lunar_exploration.py               # full NASA 2025 kit (~830 MB download)
    python lunar_exploration.py --no-hires    # skip hi-res, baseline only (~700 KB)
    python lunar_exploration.py --diviner     # + real Diviner Level-4 anomaly maps
                                                (~4 MB, needs numpy + Pillow)
    python lunar_exploration.py --port 9000   # custom port (default 8765)
    python lunar_exploration.py --no-browser  # skip auto-open
    python lunar_exploration.py --refresh     # re-download from scratch

Data sources:
  · NASA SVS CGI Moon Kit (SVS-4720)   https://svs.gsfc.nasa.gov/4720
       LROC WAC 2025 color mosaic (16-bit sRGB, Dec 2025 release)
       LOLA LDEM at 64 pixels/degree — 473 m per pixel global topography
  · UCLA Diviner Science Team           https://www.diviner.ucla.edu/data
       Level-4 bolometric temperature anomaly maps (optional)

Credits:   NASA/GSFC · Ernie Wright (USRA) · Diviner Science Team
           (D. Paige UCLA, J.-P. Williams UCLA, B. Greenhagen JHU/APL)
All NASA/USGS data is public domain. UCLA-hosted Diviner Level-4
products: please cite Williams et al. (2017), Icarus 283.
"""

import argparse
import http.server
import os
import shutil
import socketserver
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path


class C:
    ACCENT = '\033[38;5;215m'
    CORAL  = '\033[38;5;209m'
    DIM    = '\033[38;5;244m'
    OK     = '\033[38;5;114m'
    ERR    = '\033[38;5;203m'
    WARN   = '\033[38;5;221m'
    BOLD   = '\033[1m'
    RESET  = '\033[0m'


# ─── NASA SVS CGI Moon Kit ──────────────────────────────────────────────
SVS_BASE = 'https://svs.gsfc.nasa.gov/vis/a000000/a004700/a004720/'

STANDARD_ASSETS = [
    ('lroc_color_2k.jpg',       SVS_BASE + 'lroc_color_2k.jpg',
     '2K color map · LROC WAC (legacy fallback)',      447_000),
    ('lroc_color_poles_1k.jpg', SVS_BASE + 'lroc_color_poles_1k.jpg',
     '1K color map · LROC WAC 2019',                   136_000),
    ('ldem_3_8bit.jpg',         SVS_BASE + 'ldem_3_8bit.jpg',
     'Low-res displacement · LOLA LDEM (fallback)',    109_000),
]

# Hi-res tier — the "highest highest" data NASA currently offers:
#   • 2025 LROC WAC 16-bit sRGB mosaic (Dec 2025 release, way more
#     color fidelity and polar detail than the 2019 version)
#   • 64-pixel-per-degree LOLA topography (473 m per pixel — roughly
#     20× finer than the legacy 3 ppd jpg). 16-bit uint, remapped to
#     lossless 8-bit PNG so the vertex displacement stays clean.
HIRES_ASSETS = [
    ('lroc_color_16bit_srgb_4k.tif', SVS_BASE + 'lroc_color_16bit_srgb_4k.tif',
     '4K color · LROC 2025 (16-bit sRGB)',              59_000_000),
    ('lroc_color_16bit_srgb_8k.tif', SVS_BASE + 'lroc_color_16bit_srgb_8k.tif',
     '8K color · LROC 2025 (16-bit sRGB)',             232_000_000),
    ('ldem_16_uint.tif',             SVS_BASE + 'ldem_16_uint.tif',
     'LOLA topography · 16 ppd (fallback)',             32_000_000),
    ('ldem_64_uint.tif',             SVS_BASE + 'ldem_64_uint.tif',
     'LOLA topography · 64 ppd (FLAGSHIP, 473 m/px)',  506_000_000),
]

DIVINER_BASE = 'http://luna1.diviner.ucla.edu/~jpierre/diviner/level4_raster_data/'
DIVINER_ASSETS = [
    ('diviner_tbol_max_anom.xyz', DIVINER_BASE + 'diviner_tbol_max_anom.xyz',
     'Diviner max T anomaly (2 ppd)',                  2_000_000),
    ('diviner_tbol_min_anom.xyz', DIVINER_BASE + 'diviner_tbol_min_anom.xyz',
     'Diviner min T anomaly (2 ppd)',                  2_000_000),
]


BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:120.0) '
                  'Gecko/20100101 Firefox/120.0',
    'Accept':          '*/*',
    'Accept-Language': 'en-US,en;q=0.5',
    'Accept-Encoding': 'identity',
    'Referer':         'https://svs.gsfc.nasa.gov/4720',
}


def banner():
    print(f"\n{C.ACCENT}{C.BOLD}"
          f"   ┌─────────────────────────────────────────────────────┐\n"
          f"   │          L U N A R   E X P L O R A T I O N          │\n"
          f"   │     LRO imagery  ·  LOLA topography  ·  Thermal     │\n"
          f"   └─────────────────────────────────────────────────────┘{C.RESET}\n")


def progress_bar(fn, cur, total, width=30):
    if total > 0:
        filled = int(cur / total * width)
        bar = '█' * filled + '░' * (width - filled)
        pct = cur / total * 100
        sys.stdout.write(f'\r   {C.DIM}{fn:<34}{C.RESET} '
                         f'[{C.ACCENT}{bar}{C.RESET}] {pct:5.1f}%')
    else:
        sys.stdout.write(f'\r   {C.DIM}{fn:<34}{C.RESET} {cur/1e6:5.1f} MB')
    sys.stdout.flush()


def download(url, dest, fn):
    try:
        req = urllib.request.Request(url, headers=BROWSER_HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get('Content-Length', 0))
            with open(dest, 'wb') as out:
                downloaded = 0
                while True:
                    chunk = resp.read(64 * 1024)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    progress_bar(fn, downloaded, total)
        print()
        return True
    except urllib.error.HTTPError as e:
        print(f'\n   {C.ERR}✗ HTTP {e.code} — {e.reason}{C.RESET}')
        if e.code == 403:
            print(f'   {C.DIM}   Server rejected request. Corporate networks / VPNs{C.RESET}')
            print(f'   {C.DIM}   occasionally trip this. App will still run with a{C.RESET}')
            print(f'   {C.DIM}   fallback low-res texture. Source: svs.gsfc.nasa.gov/4720{C.RESET}')
        return False
    except urllib.error.URLError as e:
        print(f'\n   {C.ERR}✗ network error: {e.reason}{C.RESET}')
        return False
    except Exception as e:
        print(f'\n   {C.ERR}✗ failed: {e}{C.RESET}')
        return False


def convert_tif_to_jpg(tif_path):
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        jpg_path = tif_path.with_suffix('.jpg')
        if jpg_path.exists():
            return jpg_path
        print(f'   {C.DIM}converting {tif_path.name} → {jpg_path.name} ...{C.RESET}',
              end='', flush=True)
        im = Image.open(tif_path)
        if im.mode != 'RGB':
            im = im.convert('RGB')
        im.save(jpg_path, 'JPEG', quality=92)
        print(f' {C.OK}✓{C.RESET}')
        return jpg_path
    except ImportError:
        print(f'   {C.ERR}✗ hi-res conversion needs Pillow: pip install Pillow{C.RESET}')
        return None
    except Exception as e:
        print(f'   {C.ERR}✗ conversion failed: {e}{C.RESET}')
        return None


def convert_ldem_tif(tif_path, target_width=8192):
    """Convert LOLA uint16 elevation TIFF → 8-bit grayscale PNG.

    The uint TIFF stores elevation as 16-bit half-meter values offset
    by +20000 (so value 20000 = reference radius 1737.4 km). Lunar
    relief spans ±10 km → values ~0 to ~40000. We remap the actual
    lunar range into 0-255 so the full dynamic range is preserved in
    the 8-bit output, and downsample to WebGL-friendly size.

    PNG (lossless) matters here — JPEG DCT compression causes ringing
    around sharp crater rims that shows up as visible artifacts in the
    vertex displacement.
    """
    try:
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
    except ImportError:
        print(f'   {C.ERR}✗ LDEM conversion needs Pillow: pip install Pillow{C.RESET}')
        return None

    png_path = tif_path.with_suffix('.png')
    if png_path.exists():
        return png_path

    mb = tif_path.stat().st_size / 1e6
    print(f'   {C.DIM}converting {tif_path.name} ({mb:.0f} MB) → {png_path.name}'
          f'{C.RESET}', end='', flush=True)

    try:
        img = Image.open(tif_path)
        if img.width > target_width:
            aspect = img.height / img.width
            new_size = (target_width, int(target_width * aspect))
            # Lanczos preserves crater edges better than bilinear
            img = img.resize(new_size, Image.LANCZOS)

        try:
            import numpy as np
            arr = np.asarray(img, dtype=np.uint16)
            lo, hi = 16000, 40000   # covers full ±12 km lunar range w/ margin
            arr8 = np.clip((arr.astype(np.float32) - lo) * 255.0 / (hi - lo),
                           0, 255).astype(np.uint8)
            out = Image.fromarray(arr8, mode='L')
        except ImportError:
            out = img.convert('L')   # Pillow-only path (less precise)

        out.save(png_path, 'PNG', optimize=True)
        print(f' {C.OK}✓ {out.width}×{out.height}{C.RESET}')
        return png_path
    except Exception as e:
        print(f'\n   {C.ERR}✗ LDEM conversion failed: {e}{C.RESET}')
        return None


def diviner_xyz_to_png(xyz_path):
    """Convert a Diviner Level-4 XYZ anomaly file to a PNG heatmap."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        print(f'   {C.ERR}✗ --diviner needs numpy + Pillow. '
              f'Run: pip install numpy Pillow{C.RESET}')
        return None

    png_path = xyz_path.with_suffix('.png')
    if png_path.exists():
        return png_path

    print(f'   {C.DIM}parsing {xyz_path.name} ...{C.RESET}', end='', flush=True)
    W, H = 720, 360
    grid = np.full((H, W), np.nan, dtype=np.float32)
    try:
        with open(xyz_path, 'r') as f:
            for line in f:
                parts = line.split()
                if len(parts) < 3:
                    continue
                try:
                    lon, lat, val = float(parts[0]), float(parts[1]), float(parts[2])
                except ValueError:
                    continue
                x = int(round((lon + 180.0) * 2)) % W
                y = int(round((90.0 - lat) * 2))
                if 0 <= y < H:
                    grid[y, x] = val
    except Exception as e:
        print(f' {C.ERR}✗ parse failed: {e}{C.RESET}')
        return None

    valid = grid[~np.isnan(grid)]
    if len(valid) < 100:
        print(f' {C.ERR}✗ too few valid samples{C.RESET}')
        return None

    lo, hi = np.percentile(valid, [1, 99])
    print(f' range {lo:+.1f} … {hi:+.1f} K')

    grid[np.isnan(grid)] = (lo + hi) / 2.0
    norm = np.clip((grid - lo) / (hi - lo), 0.0, 1.0)

    import json
    meta = {
        'lo_kelvin': float(lo), 'hi_kelvin': float(hi),
        'width': W, 'height': H,
        'note': 'pixel value 0..255 maps linearly to [lo,hi] Kelvin anomaly',
    }
    with open(xyz_path.with_suffix('.meta.json'), 'w') as mf:
        json.dump(meta, mf, indent=2)

    img = Image.fromarray((norm * 255).astype(np.uint8), mode='L')
    img.save(png_path, 'PNG', optimize=True)
    print(f'   {C.OK}✓{C.RESET} wrote {png_path.name} ({W}×{H})')
    return png_path


def ensure_data(tex_dir, include_hires, include_diviner):
    tex_dir.mkdir(exist_ok=True)
    print(f'   {C.DIM}cache: {tex_dir.resolve()}{C.RESET}\n')

    assets = list(STANDARD_ASSETS)
    if include_hires:   assets += HIRES_ASSETS
    if include_diviner: assets += DIVINER_ASSETS

    for fn, url, label, _sz in assets:
        dest = tex_dir / fn
        if dest.exists() and dest.stat().st_size > 1024:
            print(f'   {C.OK}●{C.RESET} {C.DIM}{fn:<34} cached · {label}{C.RESET}')
            continue
        print(f'   {C.ACCENT}↓{C.RESET} {C.DIM}{fn:<34} · {label}{C.RESET}')
        ok = download(url, dest, fn)
        if not ok and dest.exists():
            dest.unlink()

    if include_hires:
        print()
        for fn, _, _, _ in HIRES_ASSETS:
            src = tex_dir / fn
            if not src.exists():
                continue
            if fn.startswith('ldem_'):
                convert_ldem_tif(src)
            else:
                convert_tif_to_jpg(src)

    if include_diviner:
        print()
        for fn, _, _, _ in DIVINER_ASSETS:
            xyz = tex_dir / fn
            if xyz.exists():
                diviner_xyz_to_png(xyz)

    import json
    manifest = tex_dir / 'manifest.json'
    with open(manifest, 'w') as f:
        available = sorted([
            p.name for p in tex_dir.iterdir()
            if p.suffix.lower() in {'.jpg', '.jpeg', '.png'}
        ])
        json.dump({'textures': available}, f, indent=2)

    print()


def start_server(port, root):
    os.chdir(root)

    class Q(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k): pass

    socketserver.TCPServer.allow_reuse_address = True
    try:
        httpd = socketserver.TCPServer(('', port), Q)
    except OSError:
        print(f'   {C.ERR}✗ port {port} is busy. Try --port 9001{C.RESET}')
        sys.exit(1)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    ap = argparse.ArgumentParser(
        description='Launch the Lunar Exploration 3D web app (optical + thermal).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    ap.add_argument('--no-hires',   action='store_true',
                    help='skip 4K + 8K albedo maps (saves ~60 MB; default downloads them)')
    ap.add_argument('--diviner',    action='store_true',
                    help='also download UCLA Diviner Level-4 anomaly maps')
    ap.add_argument('--port',       type=int, default=8765,
                    help='HTTP port (default 8765)')
    ap.add_argument('--no-browser', action='store_true',
                    help='do not auto-open the browser')
    ap.add_argument('--refresh',    action='store_true',
                    help='re-download everything from scratch')
    args = ap.parse_args()

    banner()

    here    = Path(__file__).resolve().parent
    tex_dir = here / 'textures'

    if args.refresh and tex_dir.exists():
        shutil.rmtree(tex_dir)

    # Hires TIFFs need Pillow to convert → JPG. Auto-skip if Pillow is absent.
    include_hires = not args.no_hires
    if include_hires:
        try:
            import PIL  # noqa: F401
        except ImportError:
            print(f'   {C.WARN}⚠ Pillow not installed — skipping 4K/8K hi-res. '
                  f'Install with: pip install Pillow{C.RESET}')
            include_hires = False

    print(f'{C.BOLD}[1/3] acquiring NASA data{C.RESET}')
    print(f'   {C.DIM}primary: NASA SVS CGI Moon Kit (SVS-4720){C.RESET}')
    if include_hires:
        print(f'   {C.DIM}hi-res:  4K + 8K polar mosaics (~60 MB){C.RESET}')
    if args.diviner:
        print(f'   {C.DIM}bonus:   UCLA Diviner Level-4 anomaly maps{C.RESET}')
    print()
    ensure_data(tex_dir, include_hires, args.diviner)

    html_path = here / 'lunar_exploration.html'
    if not html_path.exists():
        print(f'{C.ERR}✗ lunar_exploration.html not found next to this script.{C.RESET}')
        sys.exit(1)

    print(f'{C.BOLD}[2/3] starting local server{C.RESET}')
    httpd = start_server(args.port, here)
    url = f'http://localhost:{args.port}/lunar_exploration.html'
    print(f'   {C.OK}✓{C.RESET} listening on {C.ACCENT}{url}{C.RESET}\n')

    print(f'{C.BOLD}[3/3] launching interface{C.RESET}')
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
        print(f'   {C.OK}✓{C.RESET} opening in default browser\n')
    else:
        print(f'   {C.DIM}(--no-browser) open manually: {url}{C.RESET}\n')

    print(f'   {C.DIM}Ctrl+C to stop the server.{C.RESET}\n')
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f'\n{C.ACCENT}   shutting down.{C.RESET}\n')
        httpd.shutdown()


if __name__ == '__main__':
    main()
