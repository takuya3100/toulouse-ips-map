import io
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

URL = (
    "https://static.data.gouv.fr/resources/"
    "fonds-des-cartes-de-chaleur-des-taux-de-cambriolages-et-tentatives-de-cambriolages-"
    "de-logements-enregistres-par-la-police-et-la-gendarmerie-nationales/"
    "20231115-112841/2022.zip"
)

def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()

def main():
    print("Downloading SSMSI 2022 burglary map data...")
    raw = download(URL)

    try:
        import shapefile
    except ImportError:
        raise RuntimeError("pyshp is required. Add 'pip install pyshp' to the GitHub Actions workflow.")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            z.extractall(tmp)

        shp_files = list(tmp.rglob("*.shp"))
        if not shp_files:
            raise RuntimeError("No shapefile was found in the SSMSI 2022 ZIP.")

        shp = shp_files[0]
        print("  Shapefile:", shp.name)

        reader = shapefile.Reader(str(shp), encoding="utf-8")
        field_names = [f[0] for f in reader.fields[1:]]
        print("  Fields:", field_names)

        records = reader.records()
        shapes = reader.shapes()

        # Find a field whose values identify the Toulouse urban unit.
        city_field = None
        city_rows = []
        for idx, name in enumerate(field_names):
            hits = []
            for i, rec in enumerate(records):
                val = str(rec[idx] or "")
                if "toulouse" in val.lower():
                    hits.append(i)
            if hits:
                city_field = name
                city_rows = hits
                print(f"  Toulouse field: {name} ({len(hits)} records)")
                break

        if not city_rows:
            raise RuntimeError(
                "Toulouse urban unit was not found in the SSMSI shapefile. "
                f"Fields: {field_names}"
            )

        city_indices = []
        # Prefer an explicitly named class field.
        class_idx = None
        for idx, name in enumerate(field_names):
            n = name.lower()
            if "class" in n or "classe" in n:
                class_idx = idx
                break

        # Otherwise find a field containing only 1..10 for Toulouse rows.
        if class_idx is None:
            for idx, name in enumerate(field_names):
                vals = []
                ok = True
                for i in city_rows:
                    try:
                        v = float(records[i][idx])
                    except (TypeError, ValueError):
                        ok = False
                        break
                    vals.append(v)
                if ok and vals and all(v.is_integer() and 1 <= int(v) <= 10 for v in vals):
                    class_idx = idx
                    break

        if class_idx is None:
            raise RuntimeError(
                "Could not identify the 10-class field in the SSMSI shapefile. "
                f"Fields: {field_names}"
            )

        print(f"  Class field: {field_names[class_idx]}")

        # SSMSI stores the 10 classes as French text labels (for example
        # "moins de 2,9", "2,9 à ...", "plus de ..."), not as numbers.
        # Convert those labels to their ordinal class 1..10 without
        # interpreting the underlying rate ourselves.
        import re

        def class_sort_key(value):
            text = str(value or "").strip().lower().replace(",", ".")
            nums = re.findall(r"\\d+(?:\\.\\d+)?", text)
            if not nums:
                return float("inf")
            return float(nums[0])

        ordered_rows = sorted(
            city_rows,
            key=lambda i: class_sort_key(records[i][class_idx])
        )

        # The Toulouse extract should contain exactly the 10 official
        # SSMSI classes. The ordinal is only used to preserve the official
        # low-to-high class order in the map.
        if len(ordered_rows) != 10:
            raise RuntimeError(
                f"Expected 10 Toulouse SSMSI classes, got {len(ordered_rows)}."
            )

        features = []
        for ordinal, i in enumerate(ordered_rows, start=1):
            geom = shapes[i].__geo_interface__
            label = str(records[i][class_idx] or "").strip()
            features.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "class": ordinal,
                    "class_label": label,
                    "city": "Toulouse",
                    "year": 2022
                }
            })

    if not features:
        raise RuntimeError("No Toulouse burglary map features were created.")

    DATA.mkdir(parents=True, exist_ok=True)
    out = DATA / "crime_toulouse_2022.json"
    out.write_text(
        json.dumps({
            "type": "FeatureCollection",
            "features": features
        }, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8"
    )
    print("  Toulouse burglary features:", len(features))
    print("  Wrote:", out)

if __name__ == "__main__":
    main()
