import csv
import json
import os
import re
from pathlib import Path


ROOT = Path(r"C:\Users\hp\Desktop\Uni 2026A\FIT2179\A2")


def main():
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    main_js = (ROOT / "js" / "main.js").read_text(encoding="utf-8")
    ids = set(re.findall(r'id="([^"]+)"', html))
    refs = re.findall(r'"(js/vega/[^"?]+\.json)(?:\?[^"]*)?"', main_js)
    missing_specs = [ref for ref in refs if not (ROOT / ref).exists()]
    missing_containers = [
        selector[1:]
        for selector in re.findall(r'\["(#[^"]+)",\s*"js/vega/[^"]+"\]', main_js)
        if selector[1:] not in ids
    ]
    print(f"chart containers: {len(ids)}")
    print(f"vega specs referenced: {len(refs)}")
    print(f"missing specs: {missing_specs}")
    print(f"missing containers: {missing_containers}")

    for path in sorted((ROOT / "js" / "vega").glob("*.json")):
        json.loads(path.read_text(encoding="utf-8"))
    print("vega JSON parse: ok")

    for csvfile in [
        "sa2_access_summary.csv",
        "melbourne_stops.csv",
        "mode_counts.csv",
        "top_bottom_access.csv",
        "route_summary.csv",
        "hourly_service.csv",
    ]:
        rows = list(csv.DictReader((ROOT / "data" / "processed" / csvfile).open(encoding="utf-8")))
        print(f"{csvfile}: {len(rows)} rows")

    for geo in ["melbourne_sa2.geojson", "melbourne_lines.geojson"]:
        data = json.loads((ROOT / "data" / "processed" / geo).read_text(encoding="utf-8"))
        print(f"{geo}: {len(data['features'])} features")

    blank_population = []
    negative_counts = []
    bad_scores = []
    with (ROOT / "data" / "processed" / "sa2_access_summary.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["population"] == "":
                blank_population.append(row["SA2_NAME21"])
            for key in ["total_stops", "train_stops", "tram_stops", "bus_stops", "regional_stops"]:
                if int(row[key]) < 0:
                    negative_counts.append((row["SA2_NAME21"], key))
            try:
                float(row["access_score"])
            except ValueError:
                bad_scores.append(row["SA2_NAME21"])
    print(f"blank population: {blank_population}")
    print(f"negative counts: {negative_counts}")
    print(f"bad scores: {bad_scores}")

    processed_size = sum(p.stat().st_size for p in (ROOT / "data" / "processed").glob("*") if p.is_file())
    print(f"processed data size MB: {processed_size / 1024 / 1024:.2f}")


if __name__ == "__main__":
    main()
