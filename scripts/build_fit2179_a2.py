import csv
import json
import math
import os
import shutil
import struct
from collections import Counter, defaultdict
from pathlib import Path

import openpyxl


ROOT = Path(r"C:\Users\hp\Desktop\Uni 2026A\FIT2179")
SOURCE = ROOT / "a2 data"
PROJECT = ROOT / "A2"
RAW = PROJECT / "data" / "raw"
PROCESSED = PROJECT / "data" / "processed"
VEGA = PROJECT / "js" / "vega"

STOP_MODES = {
    "METRO TRAIN": "Train",
    "REGIONAL TRAIN": "Train",
    "INTERSTATE TRAIN": "Train",
    "METRO TRAM": "Tram",
    "METRO BUS": "Bus",
    "REGIONAL BUS": "Regional",
    "REGIONAL COACH": "Regional",
    "SKYBUS": "Bus",
}

PALETTE = {
    "Train": "#2364aa",
    "Tram": "#2a9d8f",
    "Bus": "#e76f51",
    "Regional": "#7b2cbf",
}


def ensure_dirs():
    for path in [
        PROJECT,
        PROJECT / "css",
        PROJECT / "js",
        VEGA,
        RAW,
        PROCESSED,
        PROJECT / "assets",
        PROJECT / "sketch",
        PROJECT / "scripts",
    ]:
        path.mkdir(parents=True, exist_ok=True)


def dbf_records(path):
    with path.open("rb") as f:
        header = f.read(32)
        n_records = struct.unpack("<I", header[4:8])[0]
        header_len = struct.unpack("<H", header[8:10])[0]
        record_len = struct.unpack("<H", header[10:12])[0]
        fields = []
        while True:
            b = f.read(32)
            if b[0] == 13:
                break
            name = b[:11].split(b"\0", 1)[0].decode("ascii", "ignore")
            fields.append((name, chr(b[11]), b[16]))
        f.seek(header_len)
        for _ in range(n_records):
            rec = f.read(record_len)
            if not rec or rec[0:1] == b"*":
                continue
            pos = 1
            row = {}
            for name, typ, length in fields:
                raw = rec[pos : pos + length].decode("latin1", "ignore").strip()
                row[name] = raw
                pos += length
            yield row


def shp_polygons(path, attrs):
    with path.open("rb") as f:
        f.seek(100)
        idx = 0
        while True:
            rec_header = f.read(8)
            if len(rec_header) < 8:
                break
            _, content_len_words = struct.unpack(">2i", rec_header)
            content = f.read(content_len_words * 2)
            shape_type = struct.unpack("<i", content[:4])[0]
            attr = attrs[idx]
            idx += 1
            if shape_type == 0:
                continue
            if shape_type not in (5, 15, 25, 31):
                continue
            xmin, ymin, xmax, ymax = struct.unpack("<4d", content[4:36])
            num_parts, num_points = struct.unpack("<2i", content[36:44])
            offset = 44
            parts = list(struct.unpack(f"<{num_parts}i", content[offset : offset + 4 * num_parts]))
            offset += 4 * num_parts
            pts = [
                struct.unpack("<2d", content[offset + i * 16 : offset + i * 16 + 16])
                for i in range(num_points)
            ]
            rings = []
            for part_idx, start in enumerate(parts):
                end = parts[part_idx + 1] if part_idx + 1 < len(parts) else num_points
                ring = pts[start:end]
                if len(ring) >= 4:
                    rings.append(ring)
            yield attr, (xmin, ymin, xmax, ymax), rings


def point_in_ring(x, y, ring):
    inside = False
    j = len(ring) - 1
    for i, (xi, yi) in enumerate(ring):
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def simplify_ring(ring, stride):
    if len(ring) <= 12:
        return [[round(x, 5), round(y, 5)] for x, y in ring]
    pts = ring[::stride]
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return [[round(x, 5), round(y, 5)] for x, y in pts]


def load_sa2():
    shp_dir = SOURCE / "SA2_2021_AUST_SHP_GDA2020"
    attrs = list(dbf_records(shp_dir / "SA2_2021_AUST_GDA2020.dbf"))
    polygons = []
    for attr, bbox, rings in shp_polygons(shp_dir / "SA2_2021_AUST_GDA2020.shp", attrs):
        if attr.get("GCC_NAME21") != "Greater Melbourne":
            continue
        polygons.append({"attr": attr, "bbox": bbox, "rings": rings})
    return polygons


def load_population():
    wb = openpyxl.load_workbook(RAW / "abs_sa2_population.xlsx", data_only=True, read_only=True)
    ws = wb["Table 2"]
    population = {}
    for row in ws.iter_rows(min_row=7, values_only=True):
        if not row or row[6] is None:
            continue
        try:
            code = str(int(row[6]))
            pop_2025 = int(row[9]) if row[9] is not None else None
            population[code] = pop_2025
        except (ValueError, TypeError):
            continue
    return population


def load_stops(sa2_polys):
    xmin = min(p["bbox"][0] for p in sa2_polys)
    ymin = min(p["bbox"][1] for p in sa2_polys)
    xmax = max(p["bbox"][2] for p in sa2_polys)
    ymax = max(p["bbox"][3] for p in sa2_polys)
    with (SOURCE / "public_transport_stops.geojson").open(encoding="utf-8") as f:
        raw = json.load(f)
    stops = []
    for feat in raw["features"]:
        props = feat["properties"]
        mode = STOP_MODES.get(props.get("MODE"))
        coords = feat.get("geometry", {}).get("coordinates") or []
        if not mode or len(coords) < 2:
            continue
        x, y = coords[0], coords[1]
        if xmin <= x <= xmax and ymin <= y <= ymax:
            stops.append(
                {
                    "stop_id": props.get("STOP_ID", ""),
                    "stop_name": props.get("STOP_NAME", ""),
                    "mode": mode,
                    "longitude": round(x, 5),
                    "latitude": round(y, 5),
                }
            )
    return stops


def assign_stops_to_sa2(sa2_polys, stops):
    counts = {
        p["attr"]["SA2_CODE21"]: {
            "total_stops": 0,
            "train_stops": 0,
            "tram_stops": 0,
            "bus_stops": 0,
            "regional_stops": 0,
        }
        for p in sa2_polys
    }
    for stop in stops:
        x, y = stop["longitude"], stop["latitude"]
        for poly in sa2_polys:
            xmin, ymin, xmax, ymax = poly["bbox"]
            if not (xmin <= x <= xmax and ymin <= y <= ymax):
                continue
            if any(point_in_ring(x, y, ring) for ring in poly["rings"]):
                code = poly["attr"]["SA2_CODE21"]
                counts[code]["total_stops"] += 1
                key = {
                    "Train": "train_stops",
                    "Tram": "tram_stops",
                    "Bus": "bus_stops",
                    "Regional": "regional_stops",
                }[stop["mode"]]
                counts[code][key] += 1
                stop["SA2_CODE21"] = code
                stop["SA2_NAME21"] = poly["attr"]["SA2_NAME21"]
                break
    return counts


def percentile(values, value):
    if not values:
        return 0
    return sum(v <= value for v in values) / len(values)


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def build_sa2_outputs(sa2_polys, population, stops, counts):
    rows = []
    for poly in sa2_polys:
        a = poly["attr"]
        code = a["SA2_CODE21"]
        c = counts[code]
        area = float(a["AREASQKM21"])
        pop = population.get(code)
        mode_diversity = sum(1 for k in ["train_stops", "tram_stops", "bus_stops", "regional_stops"] if c[k] > 0)
        rows.append(
            {
                "SA2_CODE21": code,
                "SA2_NAME21": a["SA2_NAME21"],
                "SA3_NAME21": a["SA3_NAME21"],
                "SA4_NAME21": a["SA4_NAME21"],
                "AREASQKM21": round(area, 3),
                "population": pop or 0,
                **c,
                "stops_per_sqkm": round(c["total_stops"] / area, 3) if area else 0,
                "stops_per_10000_residents": round(c["total_stops"] / pop * 10000, 3) if pop else 0,
                "mode_diversity": mode_diversity,
            }
        )
    per_capita = [r["stops_per_10000_residents"] for r in rows]
    density = [r["stops_per_sqkm"] for r in rows]
    diversity = [r["mode_diversity"] for r in rows]
    for r in rows:
        rail_bonus = 15 if r["train_stops"] > 0 else 0
        tram_bonus = 10 if r["tram_stops"] > 0 else 0
        r["per_capita_component"] = round(percentile(per_capita, r["stops_per_10000_residents"]) * 40, 1)
        r["density_component"] = round(percentile(density, r["stops_per_sqkm"]) * 25, 1)
        r["diversity_component"] = round(percentile(diversity, r["mode_diversity"]) * 10, 1)
        r["rail_component"] = rail_bonus
        r["tram_component"] = tram_bonus
        score = (
            r["per_capita_component"]
            + r["density_component"]
            + r["diversity_component"]
            + rail_bonus
            + tram_bonus
        )
        r["access_score"] = round(min(100, score), 1)
    fields = [
        "SA2_CODE21",
        "SA2_NAME21",
        "SA3_NAME21",
        "SA4_NAME21",
        "AREASQKM21",
        "population",
        "total_stops",
        "train_stops",
        "tram_stops",
        "bus_stops",
        "regional_stops",
        "stops_per_sqkm",
        "stops_per_10000_residents",
        "mode_diversity",
        "access_score",
    ]
    write_csv(PROCESSED / "sa2_access_summary.csv", rows, fields)

    top = sorted(rows, key=lambda r: r["access_score"], reverse=True)[:10]
    bottom = sorted(rows, key=lambda r: r["access_score"])[:10]
    ranked = [{**r, "rank_group": "Highest access"} for r in top] + [
        {**r, "rank_group": "Lowest access"} for r in bottom
    ]
    write_csv(PROCESSED / "top_bottom_access.csv", ranked, fields + ["rank_group"])

    component_rows = []
    components = [
        ("Stops per resident", "per_capita_component"),
        ("Stop density", "density_component"),
        ("Mode diversity", "diversity_component"),
        ("Train bonus", "rail_component"),
        ("Tram bonus", "tram_component"),
    ]
    for group, subset in [("Highest access", top[:5]), ("Lowest access", bottom[:5])]:
        for r in subset:
            for label, field in components:
                component_rows.append(
                    {
                        "SA2_NAME21": r["SA2_NAME21"],
                        "rank_group": group,
                        "component": label,
                        "contribution": r[field],
                        "access_score": r["access_score"],
                    }
                )
    write_csv(
        PROCESSED / "score_components.csv",
        component_rows,
        ["SA2_NAME21", "rank_group", "component", "contribution", "access_score"],
    )

    features = []
    row_by_code = {r["SA2_CODE21"]: r for r in rows}
    for poly in sa2_polys:
        code = poly["attr"]["SA2_CODE21"]
        props = {k: row_by_code[code][k] for k in fields}
        rings = [simplify_ring(ring, 4) for ring in poly["rings"]]
        features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": {"type": "Polygon" if len(rings) == 1 else "MultiPolygon", "coordinates": [rings[0]] if len(rings) == 1 else [[r] for r in rings]},
            }
        )
    with (PROCESSED / "melbourne_sa2.geojson").open("w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, separators=(",", ":"))
    return rows


def build_stop_outputs(stops):
    located = [s for s in stops if "SA2_CODE21" in s]
    write_csv(
        PROCESSED / "melbourne_stops.csv",
        located,
        ["stop_id", "stop_name", "mode", "longitude", "latitude", "SA2_CODE21", "SA2_NAME21"],
    )
    mode_counts = [{"mode": m, "stop_count": n} for m, n in Counter(s["mode"] for s in located).most_common()]
    write_csv(PROCESSED / "mode_counts.csv", mode_counts, ["mode", "stop_count"])


def build_route_summary():
    rows = []
    feeds = [
        ("2 - metro train", "Train"),
        ("3 - metro tram", "Tram"),
        ("4 - myki", "Bus"),
    ]
    for folder, mode in feeds:
        base = SOURCE / "gtfs" / folder
        route_names = {}
        with (base / "routes.txt").open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                route_names[r["route_id"]] = r.get("route_short_name") or r.get("route_long_name") or r["route_id"]
        trips = {}
        trip_counts = Counter()
        with (base / "trips.txt").open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                trips[r["trip_id"]] = r["route_id"]
                trip_counts[r["route_id"]] += 1
        stops_by_route = defaultdict(set)
        with (base / "stop_times.txt").open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                route_id = trips.get(r["trip_id"])
                if route_id:
                    stops_by_route[route_id].add(r["stop_id"])
        for route_id, stops in stops_by_route.items():
            rows.append(
                {
                    "mode": mode,
                    "route_name": route_names.get(route_id, route_id),
                    "stop_count": len(stops),
                    "trip_count": trip_counts[route_id],
                }
            )
    rows = sorted(rows, key=lambda r: r["trip_count"], reverse=True)[:80]
    write_csv(PROCESSED / "route_summary.csv", rows, ["mode", "route_name", "stop_count", "trip_count"])


def build_hourly_service():
    totals = Counter()
    feeds = [
        ("2 - metro train", "Train"),
        ("3 - metro tram", "Tram"),
        ("4 - myki", "Bus"),
    ]
    for folder, mode in feeds:
        base = SOURCE / "gtfs" / folder
        with (base / "stop_times.txt").open(encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                t = r.get("departure_time") or r.get("arrival_time") or ""
                if len(t) >= 2 and t[:2].isdigit() and r.get("stop_sequence") == "1":
                    totals[(int(t[:2]) % 24, mode)] += 1
    rows = [{"hour": h, "mode": m, "departures": n} for (h, m), n in sorted(totals.items())]
    write_csv(PROCESSED / "hourly_service.csv", rows, ["hour", "mode", "departures"])


def build_lines(sa2_polys):
    xmin = min(p["bbox"][0] for p in sa2_polys)
    ymin = min(p["bbox"][1] for p in sa2_polys)
    xmax = max(p["bbox"][2] for p in sa2_polys)
    ymax = max(p["bbox"][3] for p in sa2_polys)
    with (SOURCE / "public_transport_lines.geojson").open(encoding="utf-8") as f:
        raw = json.load(f)
    selected = {}
    def clipped_segments(coords):
        segment = []
        for x, y, *rest in coords:
            if xmin <= x <= xmax and ymin <= y <= ymax:
                segment.append((x, y))
            else:
                if len(segment) >= 2:
                    yield segment
                segment = []
        if len(segment) >= 2:
            yield segment

    for feat in raw["features"]:
        props = feat["properties"]
        mode = STOP_MODES.get(props.get("MODE"))
        coords = feat.get("geometry", {}).get("coordinates") or []
        if not mode or not coords:
            continue
        if not any(xmin <= x <= xmax and ymin <= y <= ymax for x, y, *rest in coords):
            continue
        base_route = props.get("SHORT_NAME") or props.get("LONG_NAME") or props.get("HEADSIGN") or ""
        for segment_idx, segment in enumerate(clipped_segments(coords)):
            key = (mode, base_route, segment_idx)
            stride = max(1, len(segment) // 120)
            simp = [[round(x, 5), round(y, 5)] for x, y in segment[::stride]]
            if len(simp) < 2:
                continue
            selected[key] = {
                "type": "Feature",
                "properties": {
                    "mode": mode,
                    "route": base_route,
                    "headsign": props.get("HEADSIGN", ""),
                    "long_name": props.get("LONG_NAME", ""),
                },
                "geometry": {"type": "LineString", "coordinates": simp},
            }
    features = list(selected.values())
    with (PROCESSED / "melbourne_lines.geojson").open("w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, separators=(",", ":"))


def spec_base(title, description=None):
    spec = {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "title": {"text": title, "anchor": "start", "fontSize": 18, "font": "Inter, Arial, sans-serif"},
        "background": "transparent",
        "config": {
            "view": {"stroke": None},
            "axis": {"labelFont": "Inter, Arial, sans-serif", "titleFont": "Inter, Arial, sans-serif"},
            "legend": {"labelFont": "Inter, Arial, sans-serif", "titleFont": "Inter, Arial, sans-serif"},
        },
    }
    if description:
        spec["description"] = description
    return spec


def write_specs():
    mode_domain = list(PALETTE)
    mode_range = [PALETTE[m] for m in mode_domain]
    specs = {}

    specs["01_network_map.json"] = {
        **spec_base("Melbourne's Public Transport Network by Mode"),
        "width": "container",
        "height": 520,
        "projection": {"type": "mercator"},
        "layer": [
            {
                "data": {"url": "data/processed/melbourne_sa2.geojson", "format": {"type": "json", "property": "features"}},
                "mark": {"type": "geoshape", "fill": "#e8eef1", "stroke": "#96a7b0", "strokeWidth": 0.7},
            },
            {
                "data": {"url": "data/processed/melbourne_lines.geojson", "format": {"type": "json", "property": "features"}},
                "mark": {"type": "geoshape", "filled": False, "strokeWidth": 2.4, "opacity": 0.95},
                "encoding": {
                    "stroke": {"field": "properties.mode", "type": "nominal", "scale": {"domain": mode_domain, "range": mode_range}, "title": "Mode"},
                    "tooltip": [{"field": "properties.route", "title": "Route"}, {"field": "properties.mode", "title": "Mode"}],
                },
            },
        ],
    }

    specs["02_stop_point_map.json"] = {
        **spec_base("Every Stop Tells a Location Story"),
        "width": "container",
        "height": 520,
        "projection": {"type": "mercator"},
        "params": [{"name": "mode_filter", "bind": {"input": "select", "options": [None] + mode_domain, "labels": ["All modes"] + mode_domain, "name": "Mode: "}}],
        "layer": [
            {"data": {"url": "data/processed/melbourne_sa2.geojson", "format": {"type": "json", "property": "features"}}, "mark": {"type": "geoshape", "fill": "#f7f8f7", "stroke": "#d6dddf", "strokeWidth": 0.4}},
            {
                "data": {"url": "data/processed/melbourne_stops.csv"},
                "transform": [{"filter": "mode_filter == null || datum.mode == mode_filter"}],
                "mark": {"type": "circle", "size": 12, "opacity": 0.52},
                "encoding": {
                    "longitude": {"field": "longitude", "type": "quantitative"},
                    "latitude": {"field": "latitude", "type": "quantitative"},
                    "color": {"field": "mode", "type": "nominal", "scale": {"domain": mode_domain, "range": mode_range}},
                    "tooltip": [{"field": "stop_name", "title": "Stop"}, {"field": "mode", "title": "Mode"}, {"field": "SA2_NAME21", "title": "SA2"}],
                },
            },
        ],
    }

    specs["03_mode_counts_bar.json"] = {
        **spec_base("Bus Stops Dominate the Stop Network"),
        "width": "container",
        "height": 310,
        "data": {"url": "data/processed/mode_counts.csv"},
        "mark": {"type": "bar", "cornerRadiusEnd": 3},
        "encoding": {
            "x": {"field": "stop_count", "type": "quantitative", "title": "Stops"},
            "y": {"field": "mode", "type": "nominal", "sort": "-x", "title": None},
            "color": {"field": "mode", "type": "nominal", "scale": {"domain": mode_domain, "range": mode_range}, "legend": None},
            "tooltip": [{"field": "mode"}, {"field": "stop_count", "format": ","}],
        },
    }

    choropleth_layer = lambda field, title, scale: {
        **spec_base(title),
        "width": "container",
        "height": 500,
        "projection": {"type": "mercator"},
        "data": {"url": "data/processed/melbourne_sa2.geojson", "format": {"type": "json", "property": "features"}},
        "mark": {"type": "geoshape", "stroke": "white", "strokeWidth": 0.35},
        "encoding": {
            "color": {"field": "properties." + field, "type": "quantitative", "scale": scale, "title": title},
            "tooltip": [
                {"field": "properties.SA2_NAME21", "title": "SA2"},
                {"field": "properties.total_stops", "title": "Total stops", "format": ","},
                {"field": "properties." + field, "title": title, "format": ".2f"},
            ],
        },
    }
    specs["04_stop_density_choropleth.json"] = choropleth_layer(
        "stops_per_sqkm",
        "Stops per Square Kilometre",
        {
            "type": "threshold",
            "domain": [5, 10, 15, 25, 40],
            "range": ["#e7f4d5", "#b8e3c4", "#75c9bd", "#33a6b8", "#1874a8", "#08306b"],
        },
    )
    specs["04_stop_density_choropleth.json"]["encoding"]["color"]["legend"] = {
        "labelExpr": "datum.value == 5 ? '< 5' : datum.value == 10 ? '5-10' : datum.value == 15 ? '10-15' : datum.value == 25 ? '15-25' : datum.value == 40 ? '25-40' : '40+'"
    }
    specs["08_population_access_choropleth.json"] = choropleth_layer("stops_per_10000_residents", "Stops per 10,000 Residents", {"type": "symlog", "constant": 10, "scheme": "yellowgreenblue"})
    specs["11_access_score_choropleth.json"] = choropleth_layer("access_score", "Overall Public Transport Access Score", {"scheme": "viridis", "domain": [0, 100]})

    specs["05_mode_small_multiples.json"] = {
        **spec_base("Where Each Mode Has a Footprint"),
        "data": {"url": "data/processed/melbourne_stops.csv"},
        "facet": {"field": "mode", "type": "nominal", "columns": 4, "title": None},
        "spec": {
            "width": 240,
            "height": 320,
            "projection": {"type": "mercator"},
            "layer": [
                {"data": {"url": "data/processed/melbourne_sa2.geojson", "format": {"type": "json", "property": "features"}}, "mark": {"type": "geoshape", "fill": "#f5f6f4", "stroke": "#d8dedb", "strokeWidth": 0.25}},
                {
                    "mark": {"type": "circle", "size": 14, "opacity": 0.7},
                    "encoding": {
                        "longitude": {"field": "longitude", "type": "quantitative"},
                        "latitude": {"field": "latitude", "type": "quantitative"},
                        "color": {"field": "mode", "type": "nominal", "scale": {"domain": mode_domain, "range": mode_range}, "legend": None},
                    },
                },
            ],
        },
    }

    specs["06_mode_mix_stacked_bar.json"] = {
        **spec_base("Mode Mix in the Largest Stop Areas"),
        "width": "container",
        "height": 390,
        "data": {"url": "data/processed/sa2_access_summary.csv"},
        "transform": [
            {"window": [{"op": "rank", "as": "rank"}], "sort": [{"field": "total_stops", "order": "descending"}]},
            {"filter": "datum.rank <= 15"},
            {"fold": ["train_stops", "tram_stops", "bus_stops", "regional_stops"], "as": ["mode_type", "stops"]},
            {"calculate": "replace(replace(replace(replace(datum.mode_type, '_stops', ''), 'train', 'Train'), 'tram', 'Tram'), 'bus', 'Bus')", "as": "mode_label"},
            {"calculate": "datum.mode_label == 'regional' ? 'Regional' : datum.mode_label", "as": "mode_label"},
        ],
        "mark": {"type": "bar"},
        "encoding": {
            "x": {"field": "SA2_NAME21", "type": "nominal", "sort": "-y", "axis": {"labelAngle": -35}, "title": None},
            "y": {"field": "stops", "type": "quantitative", "title": "Stops"},
            "color": {"field": "mode_label", "type": "nominal", "scale": {"domain": mode_domain, "range": mode_range}, "title": "Mode"},
            "tooltip": [{"field": "SA2_NAME21"}, {"field": "mode_label", "title": "Mode"}, {"field": "stops"}],
        },
    }

    specs["07_mode_coverage_dotplot.json"] = {
        **spec_base("Mode Coverage: How Many SA2s Have Each Option?"),
        "width": "container",
        "height": 280,
        "data": {"url": "data/processed/sa2_access_summary.csv"},
        "transform": [
            {"fold": ["train_stops", "tram_stops", "bus_stops", "regional_stops"], "as": ["mode_type", "stops"]},
            {"filter": "datum.stops > 0"},
            {"calculate": "replace(replace(replace(replace(datum.mode_type, '_stops', ''), 'train', 'Train'), 'tram', 'Tram'), 'bus', 'Bus')", "as": "mode_label"},
            {"calculate": "datum.mode_label == 'regional' ? 'Regional' : datum.mode_label", "as": "mode_label"},
            {"aggregate": [{"op": "count", "as": "sa2_count"}], "groupby": ["mode_label"]},
        ],
        "mark": {"type": "circle", "size": 260, "opacity": 0.9},
        "encoding": {
            "x": {"field": "sa2_count", "type": "quantitative", "title": "SA2s with at least one stop"},
            "y": {"field": "mode_label", "type": "nominal", "sort": "-x", "title": None},
            "color": {"field": "mode_label", "type": "nominal", "scale": {"domain": mode_domain, "range": mode_range}, "legend": None},
            "tooltip": [{"field": "mode_label", "title": "Mode"}, {"field": "sa2_count", "title": "SA2s"}],
        },
    }

    specs["13_mode_diversity_choropleth.json"] = {
        **spec_base("Mode Diversity Across SA2s"),
        "width": "container",
        "height": 500,
        "projection": {"type": "mercator"},
        "data": {"url": "data/processed/melbourne_sa2.geojson", "format": {"type": "json", "property": "features"}},
        "mark": {"type": "geoshape", "stroke": "white", "strokeWidth": 0.35},
        "encoding": {
            "color": {
                "field": "properties.mode_diversity",
                "type": "ordinal",
                "scale": {"domain": [1, 2, 3, 4], "range": ["#f1eef6", "#bdc9e1", "#74a9cf", "#0570b0"]},
                "title": "Modes available",
            },
            "tooltip": [
                {"field": "properties.SA2_NAME21", "title": "SA2"},
                {"field": "properties.mode_diversity", "title": "Modes available"},
                {"field": "properties.total_stops", "title": "Total stops", "format": ","},
            ],
        },
    }

    specs["09_population_vs_stops_scatter.json"] = {
        **spec_base("Population and Stop Supply Do Not Always Move Together"),
        "width": "container",
        "height": 390,
        "data": {"url": "data/processed/sa2_access_summary.csv"},
        "mark": {"type": "circle", "opacity": 0.68, "size": 70},
        "encoding": {
            "x": {"field": "population", "type": "quantitative", "title": "Population, 2025", "scale": {"type": "sqrt"}},
            "y": {"field": "total_stops", "type": "quantitative", "title": "Total stops", "scale": {"type": "sqrt"}},
            "color": {"field": "access_score", "type": "quantitative", "scale": {"scheme": "viridis"}, "title": "Access score"},
            "tooltip": [{"field": "SA2_NAME21", "title": "SA2"}, {"field": "population", "format": ","}, {"field": "total_stops"}, {"field": "access_score"}],
        },
    }

    specs["14_underserved_high_population_bar.json"] = {
        **spec_base("High-Population SA2s With Lower Stop Supply"),
        "width": "container",
        "height": 380,
        "data": {"url": "data/processed/sa2_access_summary.csv"},
        "transform": [
            {"filter": "datum.population >= 30000"},
            {"window": [{"op": "rank", "as": "rank"}], "sort": [{"field": "stops_per_10000_residents", "order": "ascending"}]},
            {"filter": "datum.rank <= 10"},
        ],
        "mark": {"type": "bar", "cornerRadiusEnd": 3},
        "encoding": {
            "x": {"field": "stops_per_10000_residents", "type": "quantitative", "title": "Stops per 10,000 residents"},
            "y": {"field": "SA2_NAME21", "type": "nominal", "sort": "x", "title": None},
            "color": {"field": "access_score", "type": "quantitative", "scale": {"scheme": "reds", "reverse": True}, "title": "Access score"},
            "tooltip": [
                {"field": "SA2_NAME21", "title": "SA2"},
                {"field": "population", "format": ","},
                {"field": "total_stops"},
                {"field": "stops_per_10000_residents", "format": ".2f"},
                {"field": "access_score"},
            ],
        },
    }

    specs["15_access_score_components.json"] = {
        **spec_base("What Drives the Final Access Score?"),
        "width": "container",
        "height": 460,
        "data": {"url": "data/processed/score_components.csv"},
        "transform": [
            {"calculate": "datum.rank_group == 'Highest access' ? 'Strongest: ' + datum.SA2_NAME21 : 'Weakest: ' + datum.SA2_NAME21", "as": "ranked_sa2"}
        ],
        "mark": {"type": "bar"},
        "encoding": {
            "x": {"field": "contribution", "type": "quantitative", "title": "Score contribution", "stack": "zero"},
            "y": {"field": "ranked_sa2", "type": "nominal", "sort": {"field": "access_score", "order": "descending"}, "title": None},
            "color": {
                "field": "component",
                "type": "nominal",
                "scale": {
                    "domain": ["Stops per resident", "Stop density", "Mode diversity", "Train bonus", "Tram bonus"],
                    "range": ["#2b8cbe", "#7bccc4", "#bae4bc", "#fdb863", "#e66101"],
                },
                "title": "Score component",
            },
            "tooltip": [{"field": "SA2_NAME21"}, {"field": "rank_group"}, {"field": "component"}, {"field": "contribution"}, {"field": "access_score"}],
        },
    }

    specs["10_ranked_access_bar.json"] = {
        **spec_base("The Highest and Lowest Access Scores"),
        "width": "container",
        "height": 430,
        "data": {"url": "data/processed/top_bottom_access.csv"},
        "mark": {"type": "bar", "cornerRadiusEnd": 3},
        "encoding": {
            "x": {"field": "access_score", "type": "quantitative", "title": "Access score"},
            "y": {"field": "SA2_NAME21", "type": "nominal", "sort": "-x", "title": None},
            "color": {"field": "rank_group", "type": "nominal", "scale": {"domain": ["Highest access", "Lowest access"], "range": ["#2a9d8f", "#d95f4f"]}, "title": None},
            "tooltip": [{"field": "SA2_NAME21"}, {"field": "rank_group"}, {"field": "access_score"}],
        },
    }

    specs["12_hourly_service_heatmap.json"] = {
        **spec_base("Service Starts Cluster Around the Daily Peaks"),
        "width": "container",
        "height": 240,
        "data": {"url": "data/processed/hourly_service.csv"},
        "mark": {"type": "rect"},
        "encoding": {
            "x": {"field": "hour", "type": "ordinal", "sort": list(range(24)), "title": "Hour of day"},
            "y": {"field": "mode", "type": "nominal", "title": None},
            "color": {"field": "departures", "type": "quantitative", "scale": {"scheme": "blues"}, "title": "Departures"},
            "tooltip": [{"field": "mode"}, {"field": "hour"}, {"field": "departures", "format": ","}],
        },
    }

    for name, spec in specs.items():
        with (VEGA / name).open("w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2)


def write_site():
    index = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Public Transport Accessibility Across Melbourne</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=Source+Serif+4:wght@600;700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="css/style.css?v=20260529g">
  <script src="https://cdn.jsdelivr.net/npm/vega@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-lite@5"></script>
  <script src="https://cdn.jsdelivr.net/npm/vega-embed@6"></script>
</head>
<body>
  <header class="hero">
    <div class="hero__inner">
      <p class="eyebrow">FIT2179 Data Visualisation 2</p>
      <h1>Public Transport Accessibility Across Melbourne</h1>
      <p class="byline">By Avishneel Sagar Narayan</p>
      <p class="lede">Melbourne's public transport network is dense in some places and thin in others. This data story compares stops, modes, population and area to ask a simple question: where does access look strongest, and where might residents need more attention?</p>
      <div class="hero__stats">
        <div><strong>2025</strong><span>ABS population year</span></div>
        <div><strong>Greater Melbourne</strong><span>SA2 analysis area</span></div>
        <div><strong>15</strong><span>Vega-Lite views</span></div>
      </div>
    </div>
  </header>

  <main>
    <section class="story-section">
      <p class="section-kicker">1. Introduction</p>
      <h2>Start with the shape of the network</h2>
      <p>Train and tram lines create strong corridors, while bus services spread access across far more suburbs. The first two maps show the difference between route structure and stop-level access.</p>
      <p>Each area in this analysis is an SA2, or Statistical Area Level 2: a small Australian Bureau of Statistics geography designed to represent local communities and suburbs. Using SA2s makes it possible to compare transport access across Greater Melbourne consistently.</p>
      <div id="network_map" class="vis large" data-note="Rail and tram routes form strong radial corridors into the inner city."></div>
      <p class="chart-note">The network map shows that rail and tram infrastructure is concentrated around strong radial corridors, while many outer areas depend on lighter, more dispersed route coverage.</p>
      <div id="stop_point_map" class="vis large" data-note="Bus stops fill many of the gaps between train and tram corridors."></div>
      <p class="chart-note">At stop level, the picture becomes denser: buses fill many of the gaps between fixed rail corridors, making them central to everyday suburban coverage.</p>
      <div id="mode_counts_bar" class="vis" data-note="Bus stops make up the largest share of Melbourne's stop network."></div>
      <p class="chart-note">The mode count comparison confirms this imbalance: bus stops dominate the network by volume, even though trains and trams often shape how people imagine Melbourne's public transport system.</p>
    </section>

    <section class="story-section">
      <p class="section-kicker">2. Stop locations</p>
      <h2>Stop density reveals the inner-city advantage</h2>
      <p>Counting stops by area highlights where public transport is physically close together. This favours compact inner SA2s, so it should be read as a spatial intensity measure rather than a complete accessibility score.</p>
      <div id="stop_density_choropleth" class="vis large" data-note="Dense inner SA2s stand out because many stops fit into small areas."></div>
      <p class="chart-note">The highest stop density appears in compact inner and middle suburbs, where many stops are packed into a small area and walking distances between services are shorter.</p>
      <div id="mode_small_multiples" class="vis large" data-note="Bus coverage is widespread; train and tram access is more corridor-based."></div>
      <p class="chart-note">Splitting the map by mode shows why density alone is not enough: bus coverage spreads widely, while train and tram stops create more selective corridors of higher-capacity access.</p>
    </section>

    <section class="story-section">
      <p class="section-kicker">3. Mode distribution</p>
      <h2>Having stops is not the same as having choices</h2>
      <p>Some areas have many stops but mostly one mode. Others have fewer stops but benefit from a stronger mode mix, especially where train or tram services sit close to buses.</p>
      <div id="mode_diversity_choropleth" class="vis large" data-note="Mode diversity highlights where residents have real choice, not just lots of stops."></div>
      <p class="chart-note">Mapping the number of available modes shows that many suburbs are bus-only, while the strongest choice tends to appear where buses overlap with train or tram access.</p>
      <div id="mode_mix_stacked_bar" class="vis" data-note="High stop totals often still depend heavily on one dominant mode."></div>
      <p class="chart-note">The stacked bars highlight that high stop totals can hide dependence on one mode, especially where bus stops make up most of the local network.</p>
      <div id="mode_coverage_dotplot" class="vis" data-note="More mode options mean more flexible access for residents."></div>
      <p class="chart-note">The coverage dot plot makes mode choice clearer: areas with multiple modes have more resilient access than places served almost entirely by a single transport type.</p>
      <div id="hourly_service_heatmap" class="vis" data-note="Service starts build through the morning and remain strong into the evening peak."></div>
      <p class="chart-note">Service timing adds another layer to access, with activity clustering around the day peaks and showing that the usefulness of a stop also depends on when services run.</p>
    </section>

    <section class="story-section">
      <p class="section-kicker">4. Population vs access</p>
      <h2>High population does not guarantee high stop supply</h2>
      <p>Normalising by population changes the picture. A suburb can look well supplied in raw stop counts but less generous once the number of residents is considered.</p>
      <div id="population_access_choropleth" class="vis large" data-note="Per-resident access changes the story by accounting for population pressure."></div>
      <p class="chart-note">When stops are compared against population, some low-population areas stand out strongly, while larger residential areas can look less well supplied per resident.</p>
      <div id="underserved_high_population_bar" class="vis" data-note="These high-population SA2s have the lowest stop supply per resident."></div>
      <p class="chart-note">Ranking only high-population SA2s draws attention to places where many residents share a comparatively small stop supply.</p>
      <div id="population_vs_stops_scatter" class="vis" data-note="Some high-population SA2s sit below the main pattern, showing weaker stop supply."></div>
      <p class="chart-note">The scatterplot reinforces the mismatch: population and stop supply increase together only loosely, so high demand does not always align neatly with high stop provision.</p>
    </section>

    <section class="story-section">
      <p class="section-kicker">5. Final access score</p>
      <h2>A simple score brings the signals together</h2>
      <p>The final score combines stops per resident, stops per square kilometre, mode diversity, and rail/tram availability. It is not an official measure, but it helps compare areas consistently and makes the trade-offs visible.</p>
      <div id="access_score_components" class="vis" data-note="The strongest SA2s combine density, per-resident supply and fixed-rail bonuses; weaker SA2s miss several ingredients."></div>
      <p class="chart-note">Breaking the score into components shows why the final ranking differs so much: high-scoring areas tend to accumulate advantages across several measures rather than winning on one measure alone.</p>
      <div id="ranked_access_bar" class="vis" data-note="The top and bottom SA2s show the clearest contrast in overall access."></div>
      <p class="chart-note">The ranked bars identify the clearest extremes, separating areas where multiple access signals stack up from those where the network appears thinner.</p>
      <div id="access_score_choropleth" class="vis large" data-note="Higher access clusters around the inner transport core; weaker scores appear more often near the fringe."></div>
      <p class="chart-note">The final map brings the story back to geography: stronger access clusters around the denser transport core, while outer areas show where distance, lower density, and fewer mode choices combine.</p>
    </section>
  </main>

  <footer>
    <div class="footer-grid">
      <section>
        <h2>AI Declaration</h2>
        <p>AI was used in this project to write python helper functions fro data processing and for streamlining some parts of the website code</p>
      </section>
      <section>
        <h2>References</h2>
        <ul class="references">
          <li><a href="https://opendata.transport.vic.gov.au/dataset/gtfs-schedule">Transport Victoria Open Data, GTFS Schedule</a> - static timetable, route, stop, trip, shape and service data.</li>
          <li><a href="https://discover.data.vic.gov.au/dataset/public-transport-lines-and-stops">Victorian Government DataVic, Public Transport Lines and Stops</a> - public transport stop and line GeoJSON spatial data.</li>
          <li><a href="https://www.abs.gov.au/statistics/people/population/regional-population/2024-25">Australian Bureau of Statistics, Regional population 2024-25</a> - SA2 estimated resident population data.</li>
          <li><a href="https://www.abs.gov.au/statistics/standards/australian-statistical-geography-standard-asgs-edition-3/jul2021-jun2026/access-and-downloads/digital-boundary-files">Australian Bureau of Statistics, ASGS Edition 3 digital boundary files</a> - 2021 SA2 boundary shapefile and area fields.</li>
          <li><a href="https://commons.wikimedia.org/wiki/File:A_class_tram_257_in_PTV_livery_operating_a_Route_12_service_to_St_Kilda_-_Fitzroy_Street_on_Macarthur_Street_crossing_Spring_Street_into_Collins_Street,_Melbourne.jpg">Hero image by Philip Mallis via Wikimedia Commons</a>, licensed under <a href="https://creativecommons.org/licenses/by-sa/2.0/">CC BY-SA 2.0</a>.</li>
        </ul>
      </section>
    </div>
  </footer>
  <script src="js/main.js?v=20260529f"></script>
</body>
</html>
"""
    css = """:root {
  --ink: #edf5f1;
  --body-copy: #c7d5d0;
  --muted: #9fb1ac;
  --line: rgba(209, 225, 219, 0.22);
  --paper: #172522;
  --panel: #ffffff;
  --panel-ink: #172026;
  --accent: #72c9b8;
  --accent-2: #2a9d8f;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  background: var(--paper);
  color: var(--ink);
  font-family: Inter, Arial, sans-serif;
  line-height: 1.6;
}

.hero {
  background: linear-gradient(120deg, rgba(12, 36, 55, 0.78), rgba(20, 96, 103, 0.58)), url("https://upload.wikimedia.org/wikipedia/commons/thumb/2/2b/A_class_tram_257_in_PTV_livery_operating_a_Route_12_service_to_St_Kilda_-_Fitzroy_Street_on_Macarthur_Street_crossing_Spring_Street_into_Collins_Street%2C_Melbourne.jpg/1280px-A_class_tram_257_in_PTV_livery_operating_a_Route_12_service_to_St_Kilda_-_Fitzroy_Street_on_Macarthur_Street_crossing_Spring_Street_into_Collins_Street%2C_Melbourne.jpg");
  background-size: cover;
  background-position: center 42%;
  color: #fff;
  min-height: 82vh;
  display: flex;
  align-items: center;
}

.hero__inner {
  text-align: center;
}

.hero__inner,
main,
footer {
  width: min(1120px, calc(100vw - 36px));
  margin: 0 auto;
}

.eyebrow,
.section-kicker {
  margin: 0 0 12px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 0.78rem;
  font-weight: 800;
}

h1,
h2 {
  font-family: "Source Serif 4", Georgia, serif;
  line-height: 1.05;
  margin: 0;
}

h1 {
  max-width: 940px;
  margin: 0 auto;
  font-size: clamp(2.6rem, 6vw, 5rem);
}

h2 {
  font-size: clamp(2rem, 4vw, 3.4rem);
  max-width: 900px;
}

.lede {
  max-width: 760px;
  margin: 22px auto 28px;
  font-size: clamp(1.05rem, 2vw, 1.35rem);
}

.byline {
  margin: 18px 0 0;
  font-size: clamp(1rem, 1.8vw, 1.28rem);
  font-weight: 700;
  letter-spacing: 0.02em;
}

.hero__stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1px;
  width: min(760px, 100%);
  margin: 0 auto;
  background: rgba(255, 255, 255, 0.28);
  border: 1px solid rgba(255, 255, 255, 0.32);
}

.hero__stats div {
  padding: 18px;
  background: rgba(0, 0, 0, 0.14);
}

.hero__stats strong,
.hero__stats span {
  display: block;
}

.hero__stats strong {
  font-size: 1.25rem;
}

.hero__stats span {
  opacity: 0.86;
  font-size: 0.92rem;
}

.story-section {
  padding: 84px 0 28px;
  border-bottom: 1px solid var(--line);
}

.story-section p {
  max-width: 780px;
  color: var(--body-copy);
  font-size: 1.02rem;
}

.section-kicker {
  color: var(--accent);
}

.vis {
  position: relative;
  width: 100%;
  margin: 28px 0 12px;
  padding: 22px;
  background: var(--panel);
  color: var(--panel-ink);
  border: 1px solid rgba(213, 226, 222, 0.72);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 18px 36px rgba(4, 12, 10, 0.28);
}

.vis.large {
  min-height: 460px;
}

.vega-embed {
  width: 100%;
}

.vega-embed > svg {
  max-width: 100%;
  height: auto;
}

.vis[data-note] {
  padding-bottom: 78px;
}

.vis[data-note]::after {
  content: attr(data-note);
  position: absolute;
  left: 22px;
  right: 22px;
  bottom: 18px;
  z-index: 3;
  padding: 12px 14px;
  color: #172026;
  background: rgba(255, 255, 255, 0.94);
  border-left: 4px solid var(--accent-2);
  border-radius: 0 8px 8px 0;
  box-shadow: 0 10px 24px rgba(24, 39, 46, 0.12);
  font-size: 0.92rem;
  font-weight: 700;
  line-height: 1.35;
  pointer-events: none;
}

.chart-note {
  margin: 0 0 34px;
  padding: 14px 18px;
  color: var(--body-copy);
  background: rgba(255, 255, 255, 0.055);
  border-left: 3px solid var(--accent);
  border-radius: 0 8px 8px 0;
}

footer {
  padding: 42px 0 64px;
  color: var(--muted);
  font-size: 0.92rem;
}

footer p {
  margin: 0 0 10px;
}

footer h2 {
  margin: 0 0 14px;
  font-family: Inter, Arial, sans-serif;
  font-size: 1.2rem;
  line-height: 1.25;
}

.footer-grid {
  display: grid;
  grid-template-columns: minmax(0, 0.8fr) minmax(0, 1.2fr);
  gap: 30px;
  padding-top: 18px;
}

.references {
  margin: 0;
  padding-left: 20px;
}

.references li {
  margin: 0 0 9px;
}

footer a {
  color: var(--accent);
}

@media (max-width: 760px) {
  .hero {
    min-height: 92vh;
  }

  .hero__stats {
    grid-template-columns: 1fr;
  }

  .story-section {
    padding-top: 58px;
  }

  .vis {
    padding: 12px;
  }

  .vis[data-note] {
    padding-bottom: 92px;
  }

  .vis[data-note]::after {
    left: 12px;
    right: 12px;
    bottom: 12px;
    font-size: 0.86rem;
  }

  .footer-grid {
    grid-template-columns: 1fr;
  }
}
"""
    main_js = """const charts = [
  ["#network_map", "js/vega/01_network_map.json?v=20260522c"],
  ["#stop_point_map", "js/vega/02_stop_point_map.json?v=20260522c"],
  ["#mode_counts_bar", "js/vega/03_mode_counts_bar.json?v=20260522c"],
  ["#stop_density_choropleth", "js/vega/04_stop_density_choropleth.json?v=20260529b"],
  ["#mode_small_multiples", "js/vega/05_mode_small_multiples.json?v=20260529b"],
  ["#mode_diversity_choropleth", "js/vega/13_mode_diversity_choropleth.json?v=20260529a"],
  ["#mode_mix_stacked_bar", "js/vega/06_mode_mix_stacked_bar.json?v=20260522c"],
  ["#mode_coverage_dotplot", "js/vega/07_mode_coverage_dotplot.json?v=20260522c"],
  ["#population_access_choropleth", "js/vega/08_population_access_choropleth.json?v=20260529b"],
  ["#underserved_high_population_bar", "js/vega/14_underserved_high_population_bar.json?v=20260529a"],
  ["#population_vs_stops_scatter", "js/vega/09_population_vs_stops_scatter.json?v=20260522c"],
  ["#access_score_components", "js/vega/15_access_score_components.json?v=20260529a"],
  ["#ranked_access_bar", "js/vega/10_ranked_access_bar.json?v=20260522c"],
  ["#access_score_choropleth", "js/vega/11_access_score_choropleth.json?v=20260522c"],
  ["#hourly_service_heatmap", "js/vega/12_hourly_service_heatmap.json?v=20260522c"]
];

const embedOptions = {
  actions: false,
  renderer: "svg"
};

charts.forEach(([target, spec]) => {
  vegaEmbed(target, spec, embedOptions).catch((error) => {
    const el = document.querySelector(target);
    if (el) {
      el.innerHTML = `<p class="error">This visualisation could not load: ${error.message}</p>`;
    }
    console.error(error);
  });
});
"""
    readme = """# Public Transport Accessibility Across Melbourne

FIT2179 Data Visualisation 2 project.

## Local preview

Open `index.html` with VS Code Live Server. The page uses Vega, Vega-Lite and Vega-Embed from CDN links, so an internet connection is needed for local preview.

## Data sources

- Public Transport Victoria GTFS and public transport spatial datasets supplied for the assignment.
- Australian Bureau of Statistics, Regional population 2024-25, data cube 32180DS0001.
- Australian Bureau of Statistics ASGS Edition 3 SA2 boundaries.

## Notes

Large raw files are intentionally excluded from the website. The page uses compact files in `data/processed`.

## Rebuilding processed data

The reproducible build script is in `scripts/build_fit2179_a2.py`. It reads the supplied raw transport and SA2 files from the local FIT2179 folder, joins ABS population data, creates compact processed files, and regenerates the Vega-Lite specs and webpage.
"""
    gitignore = """# Keep accidental huge transport files out of GitHub.
data/raw/*
!data/raw/abs_sa2_population.xlsx

# Local development noise.
.DS_Store
Thumbs.db
*.log
"""
    (PROJECT / "index.html").write_text(index, encoding="utf-8")
    (PROJECT / "css" / "style.css").write_text(css, encoding="utf-8")
    (PROJECT / "js" / "main.js").write_text(main_js, encoding="utf-8")
    (PROJECT / "README.md").write_text(readme, encoding="utf-8")
    (PROJECT / ".gitignore").write_text(gitignore, encoding="utf-8")


def copy_assets():
    draft_png = SOURCE / "draft_page_1.png"
    if draft_png.exists():
        shutil.copyfile(draft_png, PROJECT / "assets" / "draft_page_1.png")
    src_sketch = Path(r"C:\Users\hp\Downloads\fit2179 a2 draft.pdf")
    if src_sketch.exists():
        shutil.copyfile(src_sketch, PROJECT / "sketch" / "fit2179_a2_sketch.pdf")
    this_script = Path(__file__)
    verify_script = this_script.with_name("verify_fit2179_a2.py")
    if this_script.exists():
        shutil.copyfile(this_script, PROJECT / "scripts" / "build_fit2179_a2.py")
    if verify_script.exists():
        shutil.copyfile(verify_script, PROJECT / "scripts" / "verify_fit2179_a2.py")


def main():
    ensure_dirs()
    copy_assets()
    sa2_polys = load_sa2()
    population = load_population()
    stops = load_stops(sa2_polys)
    counts = assign_stops_to_sa2(sa2_polys, stops)
    rows = build_sa2_outputs(sa2_polys, population, stops, counts)
    build_stop_outputs(stops)
    build_lines(sa2_polys)
    build_route_summary()
    build_hourly_service()
    write_specs()
    write_site()
    total_size = sum(p.stat().st_size for p in PROCESSED.glob("*") if p.is_file())
    missing_pop = sum(1 for r in rows if not r["population"])
    print(f"SA2 polygons: {len(sa2_polys)}")
    print(f"Stops assigned: {sum(1 for s in stops if 'SA2_CODE21' in s)}")
    print(f"Missing population rows: {missing_pop}")
    print(f"Processed data size: {total_size / 1024 / 1024:.2f} MB")


if __name__ == "__main__":
    main()
