"""One-off script: decode world-atlas land-110m TopoJSON into plain lon/lat
polygon rings, baked into a static JSON used by cover.html's globe so it
doesn't depend on a runtime CDN fetch (which is flaky on this network).
Run manually; output is committed, this script is not imported anywhere."""
import json
import urllib.request
from pathlib import Path

URL = "https://cdn.jsdelivr.net/npm/world-atlas@2/land-110m.json"
OUT = Path(__file__).resolve().parent / "world-land.json"


def decode_arc(raw_arc, scale, translate):
    sx, sy = scale
    tx, ty = translate
    x = y = 0
    pts = []
    for dx, dy in raw_arc:
        x += dx
        y += dy
        pts.append([x * sx + tx, y * sy + ty])
    return pts


def ring_from_arc_indices(arc_indices, arcs):
    ring = []
    for ai in arc_indices:
        idx = ai if ai >= 0 else ~ai
        pts = arcs[idx]
        if ai < 0:
            pts = pts[::-1]
        if ring:
            ring.extend(pts[1:])
        else:
            ring.extend(pts)
    return ring


with urllib.request.urlopen(URL, timeout=15) as r:
    world = json.load(r)

scale = world["transform"]["scale"]
translate = world["transform"]["translate"]
arcs = [decode_arc(a, scale, translate) for a in world["arcs"]]

geoms = world["objects"]["land"]["geometries"]
rings = []
for g in geoms:
    if g["type"] == "Polygon":
        polys = [g["arcs"]]
    elif g["type"] == "MultiPolygon":
        polys = g["arcs"]
    else:
        continue
    for poly in polys:
        for ring_arc_idx in poly:
            ring = ring_from_arc_indices(ring_arc_idx, arcs)
            if len(ring) > 6:
                rings.append(ring)

# Simplify: keep every Nth point per ring to keep file small, preserve closure.
def simplify(ring, step=2):
    if len(ring) <= 20:
        return ring
    out = ring[::step]
    if out[-1] != ring[-1]:
        out.append(ring[-1])
    return out

rings = [simplify(r) for r in rings]
rings = [[[round(lo, 2), round(la, 2)] for lo, la in r] for r in rings]

OUT.write_text(json.dumps(rings, separators=(",", ":")))
print(f"wrote {len(rings)} rings, {OUT.stat().st_size} bytes -> {OUT}")
