import csv
import io
import json
import re
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

TOULOUSE = "31555"

INSEE_URLS = {
    "population": "https://www.insee.fr/fr/statistiques/fichier/8647014/base-ic-evol-struct-pop-2022_csv.zip",
    "families": "https://www.insee.fr/fr/statistiques/fichier/8647008/base-ic-couples-familles-menages-2022_csv.zip",
    "housing": "https://www.insee.fr/fr/statistiques/fichier/8647012/base-ic-logement-2022_csv.zip",
    "income": "https://www.insee.fr/fr/statistiques/fichier/8229323/BASE_TD_FILO_IRIS_2021_DISP_CSV.zip",
}

# Geometry is fetched from the official IGN WFS service.
# The 2022 INSEE population/family/housing data use the geography
# in force on 2024-01-01. The IGN IRIS layer is used only for geometry.
IRIS_WFS_URL = "https://data.geopf.fr/wfs/ows"
IRIS_WFS_TYPENAME = "STATISTICALUNITS.IRIS:contours_iris"

def download(url):
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "toulouse-ips-map/1.0"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()

def read_zip_csv(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [
            n for n in z.namelist()
            if n.lower().endswith(".csv")
            and not n.endswith("/")
        ]
        if not names:
            raise RuntimeError("CSVがZIP内に見つかりません")
        # Prefer the largest CSV; documentation/helper CSVs are normally much smaller.
        name = max(names, key=lambda n: z.getinfo(n).file_size)
        raw = z.read(name)

    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RuntimeError("CSVの文字コードを判定できません")

    sample = text[:10000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,|\t")
        delimiter = dialect.delimiter
    except csv.Error:
        delimiter = ";"

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    return reader.fieldnames or [], reader

def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())

def find_field(fields, candidates):
    by_norm = {norm(f): f for f in fields}
    for c in candidates:
        if norm(c) in by_norm:
            return by_norm[norm(c)]
    # Fallback: exact normalized prefix/contains match.
    for f in fields:
        nf = norm(f)
        for c in candidates:
            nc = norm(c)
            if nf == nc or nf.endswith(nc) or nc in nf:
                return f
    return None

def to_num(v):
    if v is None:
        return None
    s = str(v).strip().replace("\u202f", "").replace(" ", "")
    if s in ("", "NA", "ND", "nd", "s", "ns", "///"):
        return None
    try:
        return float(s.replace(",", "."))
    except ValueError:
        return None

def ratio(num, den):
    if num is None or den in (None, 0):
        return None
    return round(num / den * 100, 2)

def clean_code(v):
    return str(v or "").strip().zfill(5)

def iris_code_from_row(row, fields):
    f = find_field(fields, ["IRIS", "CODE_IRIS", "CODGEO"])
    if not f:
        return None
    value = str(row.get(f) or "").strip()
    if len(value) == 9 and value[:5] == TOULOUSE:
        return value
    # Some Filosofi files use CODGEO as the 9-digit IRIS code.
    if len(value) >= 9 and value[:5] == TOULOUSE:
        return value[:9]
    return None

def read_population():
    fields, reader = read_zip_csv(download(INSEE_URLS["population"]))
    required = {
        "iris": find_field(fields, ["IRIS"]),
        "population": find_field(fields, ["P22_POP"]),
        "a0014": find_field(fields, ["P22_POP0014"]),
        "a1529": find_field(fields, ["P22_POP1529"]),
        "a3044": find_field(fields, ["P22_POP3044"]),
        "a4559": find_field(fields, ["P22_POP4559"]),
        "a6074": find_field(fields, ["P22_POP6074"]),
        "a75p": find_field(fields, ["P22_POP75P"]),
    }
    if not all(required.values()):
        raise RuntimeError(f"Population variables not found: {required}")

    out = {}
    for row in reader:
        if clean_code(row.get(find_field(fields, ["COM"]))) != TOULOUSE:
            continue
        iris = str(row.get(required["iris"]) or "").strip()
        if len(iris) != 9:
            continue
        total = to_num(row.get(required["population"]))
        out[iris] = {
            "population": total,
            "age_0_14": ratio(to_num(row.get(required["a0014"])), total),
            "age_15_29": ratio(to_num(row.get(required["a1529"])), total),
            "age_30_44": ratio(to_num(row.get(required["a3044"])), total),
            "age_45_59": ratio(to_num(row.get(required["a4559"])), total),
            "age_60_74": ratio(to_num(row.get(required["a6074"])), total),
            "age_75_plus": ratio(to_num(row.get(required["a75p"])), total),
        }
    return out

def read_families():
    fields, reader = read_zip_csv(download(INSEE_URLS["families"]))
    com_field = find_field(fields, ["COM"])
    iris_field = find_field(fields, ["IRIS"])
    men = find_field(fields, ["C22_MEN"])
    single = find_field(fields, ["C22_MENPSEUL"])
    couple_child = find_field(fields, ["C22_MENCOUPAENF"])
    mono = find_field(fields, ["C22_MENFAMMONO"])
    required = [com_field, iris_field, men, single, couple_child, mono]
    if not all(required):
        raise RuntimeError(f"Family variables not found: {required}")

    out = {}
    for row in reader:
        if clean_code(row.get(com_field)) != TOULOUSE:
            continue
        iris = str(row.get(iris_field) or "").strip()
        if len(iris) != 9:
            continue
        total = to_num(row.get(men))
        single_n = to_num(row.get(single))
        child_n = (to_num(row.get(couple_child)) or 0) + (to_num(row.get(mono)) or 0)
        mono_n = to_num(row.get(mono))
        out[iris] = {
            "single_household": ratio(single_n, total),
            "child_household": ratio(child_n, total),
            "single_parent_household": ratio(mono_n, total),
        }
    return out

def read_housing():
    fields, reader = read_zip_csv(download(INSEE_URLS["housing"]))
    com_field = find_field(fields, ["COM"])
    iris_field = find_field(fields, ["IRIS"])
    rp = find_field(fields, ["P22_RP"])
    house = find_field(fields, ["P22_RPMAISON"])
    owner = find_field(fields, ["P22_RP_PROP"])
    hlm = find_field(fields, ["P22_RP_LOCHLMV"])
    old_fields = [
        find_field(fields, ["P22_RP_ACH1919"]),
        find_field(fields, ["P22_RP_ACH1945"]),
        find_field(fields, ["P22_RP_ACH1970"]),
        find_field(fields, ["P22_RP_ACH1990"]),
    ]
    required = [com_field, iris_field, rp, house, owner, hlm, *old_fields]
    if not all(required):
        raise RuntimeError(f"Housing variables not found: {required}")

    out = {}
    for row in reader:
        if clean_code(row.get(com_field)) != TOULOUSE:
            continue
        iris = str(row.get(iris_field) or "").strip()
        if len(iris) != 9:
            continue
        total = to_num(row.get(rp))
        old = sum((to_num(row.get(f)) or 0) for f in old_fields)
        out[iris] = {
            # "old" = principal residences built before 1991.
            "old_housing": ratio(old, total),
            "house_rate": ratio(to_num(row.get(house)), total),
            "owner_rate": ratio(to_num(row.get(owner)), total),
            "hlm_rate": ratio(to_num(row.get(hlm)), total),
        }
    return out

def read_income():
    blob = download(INSEE_URLS["income"])

    # The INSEE Filosofi ZIP contains multiple CSV files. In particular,
    # one of them is the variable dictionary with headers such as
    # COD_VAR/LIB_VAR/LIB_VAR_LONG. We must select the actual IRIS data CSV
    # by its headers rather than assuming the largest/first CSV is the data.
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [
            n for n in z.namelist()
            if n.lower().endswith(".csv") and not n.endswith("/")
        ]
        if not names:
            raise RuntimeError("No CSV found in income ZIP")

        selected = None
        selected_fields = None
        selected_reader = None

        for name in names:
            raw = z.read(name)
            decoded = None
            for enc in ("utf-8-sig", "cp1252", "latin-1"):
                try:
                    decoded = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    pass
            if decoded is None:
                continue

            sample = decoded[:10000]
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=";,|\\t")
                delimiter = dialect.delimiter
            except csv.Error:
                delimiter = ";"

            reader = csv.DictReader(io.StringIO(decoded), delimiter=delimiter)
            fields = reader.fieldnames or []

            iris_field = find_field(fields, ["IRIS", "CODE_IRIS", "CODGEO"])
            med = find_field(
                fields,
                ["DISP_MED_A21", "DISP_MED", "MED", "MEDIANE", "MEDIAN"]
            )
            poverty = find_field(
                fields,
                ["DISP_TP60_A21", "DISP_TP60", "TP60", "TAUXPAUV", "POV"]
            )

            if iris_field and med and poverty:
                selected = name
                selected_fields = fields
                selected_reader = reader
                break

        if selected_reader is None:
            raise RuntimeError(
                "Could not find the IRIS income data CSV in the INSEE ZIP. "
                f"CSV files found: {names}"
            )

        print(f"  Income data CSV: {selected}")

        iris_field = find_field(
            selected_fields, ["IRIS", "CODE_IRIS", "CODGEO"]
        )
        med = find_field(
            selected_fields,
            ["DISP_MED_A21", "DISP_MED", "MED", "MEDIANE", "MEDIAN"]
        )
        poverty = find_field(
            selected_fields,
            ["DISP_TP60_A21", "DISP_TP60", "TP60", "TAUXPAUV", "POV"]
        )

        out = {}
        for row in selected_reader:
            iris = iris_code_from_row(row, selected_fields)
            if not iris:
                continue
            out[iris] = {
                "living_standard": to_num(row.get(med)),
                "poverty_rate": to_num(row.get(poverty)),
            }

    return out

def load_geometry():
    """Fetch Toulouse IRIS polygons from the official IGN WFS.

    The IGN WFS rejects the CQL_FILTER used by the previous version.
    We therefore use a geographic BBOX to retrieve the IRIS polygons
    around Toulouse, then filter the returned features by INSEE commune/
    IRIS code in Python.
    """
    import urllib.parse

    # Approximate Toulouse city bounding box in WGS84.
    # The final selection is still done by INSEE commune/IRIS code.
    bbox = "1.35,43.50,1.55,43.70"

    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": IRIS_WFS_TYPENAME,
        "SRSNAME": "EPSG:4326",
        "OUTPUTFORMAT": "application/json",
        "BBOX": bbox + ",EPSG:4326",
        "COUNT": "1000",
    }

    url = IRIS_WFS_URL + "?" + urllib.parse.urlencode(params)
    raw = download(url)
    obj = json.loads(raw.decode("utf-8"))

    all_features = obj.get("features") or []
    print(f"  IGN IRIS WFS BBOX returned: {len(all_features)} features")

    features = []

    for feature in all_features:
        if not isinstance(feature, dict):
            continue

        props = feature.get("properties") or {}

        iris = str(
            props.get("CODE_IRIS")
            or props.get("code_iris")
            or props.get("CODEIRIS")
            or props.get("IRIS")
            or ""
        ).strip()

        com = str(
            props.get("INSEE_COM")
            or props.get("insee_com")
            or props.get("DEPCOM")
            or props.get("CODE_COM")
            or ""
        ).strip()

        # Toulouse IRIS codes are 9 digits and start with commune code 31555.
        # Prefer the IRIS code because it is the stable join key used by
        # the INSEE statistical datasets.
        if not iris.startswith(TOULOUSE):
            continue
        if len(iris) != 9:
            continue
        if com and com != TOULOUSE:
            continue

        geometry = feature.get("geometry")
        if not isinstance(geometry, dict) or not geometry.get("type"):
            continue

        features.append({
            "type": "Feature",
            "geometry": geometry,
            "properties": {
                "iris": iris,
                "name": (
                    props.get("NOM_IRIS")
                    or props.get("nom_iris")
                    or props.get("LIBIRIS")
                    or iris
                ),
                "commune": "Toulouse",
            },
        })

    unique = {}
    for feature in features:
        unique[feature["properties"]["iris"]] = feature

    features = list(unique.values())

    print(f"  Toulouse IRIS geometry features: {len(features)}")

    if len(features) < 100:
        raise RuntimeError(
            f"Only {len(features)} Toulouse IRIS geometries were returned; "
            "expected roughly 150. Aborting to avoid publishing incomplete data."
        )

    return features

def main():
    DATA.mkdir(parents=True, exist_ok=True)

    print("Downloading INSEE 2022 population data...")
    population = read_population()
    print(f"  Toulouse IRIS: {len(population)}")

    print("Downloading INSEE 2022 household data...")
    families = read_families()
    print(f"  Toulouse IRIS: {len(families)}")

    print("Downloading INSEE 2022 housing data...")
    housing = read_housing()
    print(f"  Toulouse IRIS: {len(housing)}")

    print("Downloading INSEE 2021 Filosofi income data...")
    income = read_income()
    print(f"  Toulouse IRIS: {len(income)}")

    print("Downloading 2024 IRIS geometry...")
    geometry = load_geometry()
    print(f"  Geometry features: {len(geometry)}")

    # ③ Resident / household composition: 2022, IRIS geography 2024.
    features_community = []
    for feature in geometry:
        iris = feature["properties"]["iris"]
        props = dict(feature["properties"])
        props.update(population.get(iris, {}))
        props.update(families.get(iris, {}))
        features_community.append({
            "type": "Feature",
            "geometry": feature["geometry"],
            "properties": props,
        })

    # ④ Housing: 2022, IRIS geography 2024.
    features_housing = []
    for feature in geometry:
        iris = feature["properties"]["iris"]
        props = dict(feature["properties"])
        props.update(housing.get(iris, {}))
        features_housing.append({
            "type": "Feature",
            "geometry": feature["geometry"],
            "properties": props,
        })

    # ④ Income: Filosofi 2021 is published in 2022 geography.
    # We use the current 2024 geometry where the IRIS code still exists.
    # The script reports unmatched income IRIS rather than inventing a spatial conversion.
    features_income = []
    income_unmatched = 0
    for feature in geometry:
        iris = feature["properties"]["iris"]
        if iris not in income:
            income_unmatched += 1
            continue
        props = dict(feature["properties"])
        props.update(income[iris])
        features_income.append({
            "type": "Feature",
            "geometry": feature["geometry"],
            "properties": props,
        })

    def write(name, features):
        path = DATA / name
        path.write_text(
            json.dumps(
                {"type": "FeatureCollection", "features": features},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        print(f"Wrote {len(features)} features -> {path}")

    write("iris_community.json", features_community)
    write("iris_housing.json", features_housing)
    write("iris_income.json", features_income)

    print(f"Income IRIS without matching 2024 geometry: {income_unmatched}")
    print("INSEE map data update completed.")

if __name__ == "__main__":
    main()
