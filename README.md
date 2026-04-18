# Lunar Exploration 🌕

View it live at **[emaadparacha.com/astro/moon](https://emaadparacha.com/astro/moon)**. 🌑

A 3D web app of the Moon with two views in one — optical imagery from
the Lunar Reconnaissance Orbiter, and a physics-based thermal model
calibrated to Diviner observations. Toggle between them, toggle the sun
on and off, and inspect anywhere with a hover probe.

Real 3D terrain (craters bulge out, mountains cast shadows on the
limb), a thermal model with inertia lag and rock abundance, and a
subsurface temperature probe down to 1 m.

One command does everything — downloads the NASA data, starts a local
server, opens the viewer.

```
python3 lunar_exploration.py
```

---

## The toggles

**VIEW** — Optical or Thermal. The two big buttons top-left.

Tap the **VIEW** or **PARAMETERS** panel title to collapse that panel
(the caret rotates to indicate state). On phone-sized screens both
panels start collapsed so they don't cover the sphere; tap to expand
as needed.

- **OPTICAL** renders the LROC Wide Angle Camera mosaic on LOLA
  topography. What the Moon actually looks like.
- **THERMAL** replaces the imagery with a per-pixel surface temperature
  field, color-coded from 25 K (deep violet) to 400 K (white-hot).

**SUN** — On or Off. The switch at the top of the right panel.

- **ON** — the sun illuminates the scene. In optical mode that means
  shadows and a terminator; in thermal mode that means the temperature
  field responds to where the sun currently is.
- **OFF** — no sun. Optical mode shows a "full moon" view, every
  feature visible, no shadows. Thermal mode switches automatically to
  **Diurnal Maximum** (the hottest each point ever gets across a full
  lunation).

**3D RELIEF** — checkbox in the parameters panel. Coupled to the
TERRAIN RELIEF slider.

- **ON** — vertices of the sphere are displaced outward along their
  normals by the LOLA height map. Crater rims, mountain ridges, and
  basin floors have real geometry; shadows on the limb show them.
- **OFF** — sphere stays perfectly smooth. Shading still makes the
  surface look bumpy via normal-mapping, but the silhouette is clean.

**ISOTHERMS** — checkbox in the parameters panel, thermal-only. Draws
50 K anti-aliased contour lines on the thermal field. Major 100 K
lines are emphasized.

Each view has its own sub-controls that appear under the master toggle:

- Optical sub-panel: imagery resolution (1K / 2K / 4K / 8K — all four
  downloaded by default; pass `--no-hires` to skip the 4K/8K TIFFs).
- Thermal sub-panel: Instantaneous / Lunation (animated) / Diurnal Max
  / Diurnal Min / PSR Highlight.

---

## Hover probe

Move the cursor anywhere on the sphere. A floating readout shows:

- lat/lon of the point under your cursor
- local Bond albedo sampled from the LROC texture
- **in thermal mode:** model temperature in K, °C, and °F, plus a
  subsurface depth profile at 0 cm / 1 cm / 10 cm / 1 m

The subsurface profile uses a Vasavada-style exponential damping of
the diurnal thermal wave with skin depth ≈ 5 cm — so at 1 m you'll
see essentially the local annual-mean temperature, which varies with
latitude and stays remarkably constant against the surface's ±200 K
day/night swing.

---

## Command line

```
python3 lunar_exploration.py               # full kit w/ 4K + 8K (~60 MB, needs Pillow)
python3 lunar_exploration.py --no-hires    # skip hi-res, 2K only (~700 KB)
python3 lunar_exploration.py --diviner     # + real Diviner Level-4 anomaly
                                             maps (~4 MB, needs numpy + Pillow)
python3 lunar_exploration.py --port 9000   # custom port (default 8765)
python3 lunar_exploration.py --no-browser  # skip auto-open
python3 lunar_exploration.py --refresh     # re-download everything
```

Hi-res is on by default. If Pillow isn't installed the launcher skips
conversion automatically and falls back to the standard 2K mosaic — no
flag change required.

The script caches downloads in a `textures/` folder next to itself and
writes a `manifest.json` that the viewer reads to know which
resolutions are available. Cached files aren't re-downloaded on repeat
runs.

---

## Physics (thermal view)

The fragment shader computes temperature per pixel from first
principles, layered with several second-order corrections that make the
field match Diviner observations more closely than a bare equilibrium
model.

Dayside — radiative equilibrium:

```
absorbed = (1 − A) · S · max(cos θ, 0)      [W/m²]
emitted  = ε · σ · T⁴                        [W/m²]
⇒ T_day = [absorbed / (ε·σ)] ^ (1/4)
```

with `S = 1361 W/m²` (solar constant), `ε = 0.95` (lunar emissivity),
`σ = 5.67×10⁻⁸` (Stefan-Boltzmann), and `A = 0.04 + 0.22·L` (Bond
albedo from LROC luminance). The subsolar peak at average highland
albedo comes out to ~386 K, which matches the 387-397 K Diviner
reports.

**Thermal inertia lag.** Real regolith can't equilibrate
instantaneously with changing insolation, so the peak temperature
trails the subsolar point by ~15° of longitude (roughly one lunar
hour past noon). The shader rotates the effective sun direction
backward by this angle before the dot-product, so the hot spot sits
east of the literal subsolar point — same as what Diviner sees.

**Rock abundance.** Fresh ejecta and boulder fields retain heat
overnight because rock has higher thermal inertia than fine regolith.
The shader derives a rock-abundance index from local albedo plus the
displacement-map gradient (proxy for surface roughness), and uplifts
nightside T by up to 28 K where rock is abundant. This is the same
mechanism that makes Tycho's ejecta rays glow on Diviner nightside
maps.

Nightside — cools on regolith thermal-inertia timescales of Earth-days.
Approximated by:

```
T_night(cos θ) = 95 K + 105 K · (1 + cos θ) + rock_idx · 28 K
```

giving ~200 K just past the terminator (recently-set regolith) and
~95 K near the antisolar point — matches Williams et al. (2017).
Rocky spots get an extra boost.

**Subsurface thermal wave.** The hover probe shows temperature at
depth using the classical exponential damping of the diurnal wave:

```
T(z, t) = T_mean(lat) + (T_surface − T_mean(lat)) · exp(−z / δ)
```

with skin depth `δ ≈ 5 cm`. At 1 m, almost all the diurnal signal has
died away, so T stays near the latitude's mean value (~220 K
equatorial, dropping toward polar mean as cos(lat)) regardless of
whether the surface is frozen or blazing.

**Terrain self-shadowing** is the mechanism by which real polar PSRs
stay cold. The shader samples the LOLA displacement map four times
(finite differences on height) to bump the surface normal, so a crater
wall tipped away from the sun gets `cos θ < 0` and drops to the night
curve even on the "day" side of the Moon.

**Diurnal extremes** exploit the Moon's near-zero axial tilt (1.5°).
Over a lunation the subsolar direction sweeps the equatorial plane, so
for a point with normal `N = (nx, ny, nz)` the max `cos θ` it ever sees
is `sqrt(nx² + nz²)`. That closed-form gives Diurnal Max and Min in one
shader pass.

---

## Data sources

### Primary (downloaded automatically, ~830 MB full kit)

- **LROC WAC 2025 color mosaic** — released Dec 2025 as 16-bit sRGB TIFF.
  Dramatically better polar detail and dynamic range than the 2019
  version. Downloaded at both 4K (59 MB) and 8K (232 MB).
- **LOLA LDEM at 64 pixels per degree** — 473 m per pixel global
  topography (the highest-resolution global DEM NASA publishes in a
  single mosaic, beneath SLDEM2015). 506 MB download; the launcher
  remaps the 16-bit elevation range into an 8K PNG (~25 MB cached) so
  the WebGL vertex shader can drive real crater geometry from it.
- Baseline low-res fallbacks (2K color, 3 ppd displacement) always
  download first so the app works even if the hires transfer fails.

Both come from NASA SVS-4720: <https://svs.gsfc.nasa.gov/4720>.

Pass `--no-hires` to skip everything over ~1 MB. Pass `--refresh` to
re-download with the new 2025 URLs if your cache has the 2019 assets.

### Optional (`--diviner`)

- **Diviner Level-4 bolometric temperature anomaly maps**, 2 px/°,
  from the UCLA Diviner Science Team:
  `http://luna1.diviner.ucla.edu/~jpierre/diviner/level4_raster_data/`

These are ASCII `lon lat value` triples. The launcher parses them into
a 720×360 grid and writes a PNG (plus a JSON sidecar with the Kelvin
range) suitable for overlay. If you use them in publications, cite:
Williams, J.-P., D. A. Paige, B. T. Greenhagen, E. Sefton-Nash (2017).
*The global surface temperatures of the Moon as measured by the Diviner
Lunar Radiometer Experiment.* Icarus 283.

---

## Requirements

- **Python 3.6+** — only the standard library is needed for the basic
  flow. Hi-res imagery (on by default) needs `pip install Pillow`; the
  launcher detects its absence and falls back to 2K automatically.
  `--diviner` needs `pip install numpy Pillow`.
- **A modern browser** — Chrome, Firefox, Safari, or Edge. The viewer
  uses WebGL (both 1 and 2 supported), ES modules, and importmaps.

---

## What the model still doesn't capture

The thermal view now has inertia lag, rock-abundance uplift, and a
subsurface wave, but several second-order effects are still missing:

- **Horizontal heat transport** — none. Each pixel is independent.
  Fine for the Moon's near-vacuum surface but unrealistic for Earth.
- **Full Vasavada/Hayne regolith model** — the real two-layer
  insulating regolith over a conductive rock basement produces
  slightly different subsurface profiles than the single-skin-depth
  exponential we use here. Good enough for intuition, not for a paper.
- **IR self-illumination in deep craters** — a crater floor in
  geometric shadow still receives IR emission from sunlit walls, which
  slightly warms PSRs above pure-vacuum equilibrium. The 40 K PSR
  floor is calibrated to account for this empirically rather than
  physically.
- **Actual Diviner rock-abundance product** — we infer rock abundance
  from LROC albedo and LOLA gradient, not from Diviner's two-channel
  thermal inversion. Close, not identical.

For research use, pull the actual Diviner data products from PDS
directly (or UCLA's Level-4 products via `--diviner`). This app is a
visualization and pedagogical tool, not a research instrument.

---

## Attribution

All data is public domain, produced by:

- **NASA/Goddard Space Flight Center** · Scientific Visualization
  Studio (Ernie Wright, Noah Petro)
- **LROC team** at Arizona State University
- **LOLA team** at Goddard / MIT
- **Diviner Science Team**: David Paige (PI, UCLA), J.-P. Williams,
  Benjamin Greenhagen (APL), and the broader team

Cite as appropriate:
- NASA/GSFC SVS, CGI Moon Kit, <https://svs.gsfc.nasa.gov/4720>
- Williams et al. (2017), *Icarus* 283 — for the thermal physics

---

## Troubleshooting

**NASA download 403.** Some corporate networks and VPNs trip NASA SVS's
bot filter. The app still launches with a fallback low-res texture so
you can see something. Try again from a home connection, or download
the JPGs manually from <https://svs.gsfc.nasa.gov/4720> into a
`textures/` folder next to the script.

**"Port 8765 busy."** Another process is bound to it. Use
`--port 9000` (or any free port).

**Moon looks flat.** Turn up the **TERRAIN RELIEF** slider. The LOLA
map is 8-bit so visible relief requires exaggeration; ×2 to ×3 is a
good default.

**Blank canvas.** Open DevTools (F12) → Console. If you see a shader
compile error, grab the text and file it as an issue. The viewer has a
remote-CDN fallback texture so even without NASA data it should render
*something*.

**Probe shows "—" always.** Mouse is not hitting the sphere. The
ray-caster intersects the base sphere, not the displaced geometry, so
hover should register anywhere on the visible disk.
---

## License

Copyright (c) 2026 Emaad Paracha. All rights reserved.

No permission is granted to use, copy, modify, distribute, sublicense,
publish, or create derivative works from this software without prior
written permission from the copyright holder.

For permission requests, contact: [your email]

