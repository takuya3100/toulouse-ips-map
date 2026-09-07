import json
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/"
DATASETS = {
    "directory": "fr-en-annuaire-education",
    "elementaire": "fr-en-ips-ecoles-ap2022",
    "college": "fr-en-ips-colleges-ap2023",
    "lycee": "fr-en-ips-lycees-ap2023",
}

OUT = Path(__file__).resolve().parents[1] / "data" / "schools.json"


def get(dataset, where):
    params = urllib.parse.urlencode({"where": where, "limit": 10000})
    url = BASE + dataset + "/records?" + params
    print(f"GET {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "toulouse-ips-map/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        payload = json.load(r)
    return payload.get("results", [])


def first(row, *names):
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def truthy(value):
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "oui", "y"}


def to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def school_year(value):
    if value in (None, ""):
        return ""
    text = str(value).strip()
    # 2025-2026 -> 2025, which matches the map's year selector convention.
    return text[:4] if len(text) >= 4 and text[:4].isdigit() else text


def normalize_sector(value):
    text = str(value or "").strip().lower()
    return "Privé" if "priv" in text else "Public"


def infer_type(directory_row):
    # The national directory exposes separate flags for maternelle/elementaire
    # and secondary school pathways. Prefer the most specific school type.
    if truthy(directory_row.get("Ecole_maternelle")) and not truthy(directory_row.get("Ecole_elementaire")):
        return "maternelle"
    if truthy(directory_row.get("Ecole_elementaire")):
        return "elementaire"

    type_etab = str(directory_row.get("Type_etablissement") or "").strip().lower()
    if "coll" in type_etab:
        return "college"
    if any(truthy(directory_row.get(k)) for k in ("Voie_generale", "Voie_technologique", "Voie_professionnelle")):
        return "lycee"

    nature = str(directory_row.get("libelle_nature") or "").lower()
    if "collège" in nature or "college" in nature:
        return "college"
    if "lycée" in nature or "lycee" in nature:
        return "lycee"
    if "maternelle" in nature:
        return "maternelle"
    if "élémentaire" in nature or "elementaire" in nature:
        return "elementaire"
    return None


def ips_value(row, kind):
    if kind == "elementaire":
        return to_float(first(row, "ips"))
    if kind == "college":
        return to_float(first(row, "ips", "ips_etablissement"))
    if kind == "lycee":
        return to_float(first(row, "ips_etab", "ips_de_l_etablissement", "ips_ensemble_gt_pro", "ips_ensemble_gt_pro"))
    return None


def main():
    print("Fetching Toulouse school directory...")
    directory_rows = get(DATASETS["directory"], 'Nom_commune="TOULOUSE"')
    print(f"Directory records: {len(directory_rows)}")

    directory = {}
    for row in directory_rows:
        uai = first(row, "Identifiant_de_l_etablissement", "uai", "UAI")
        lat = to_float(first(row, "latitude"))
        lon = to_float(first(row, "longitude"))
        if not uai or lat is None or lon is None:
            continue
        directory[str(uai)] = {
            "uai": str(uai),
            "name": first(row, "Nom_etablissement", "nom_etablissement") or "",
            "sector": normalize_sector(first(row, "Statut_public_prive", "secteur")),
            "type": infer_type(row),
            "lat": lat,
            "lon": lon,
        }

    # Build all IPS records by UAI and school year.
    sources = [
        ("elementaire", 'nom_de_la_commune="TOULOUSE"'),
        ("college", 'nom_de_la_commune="TOULOUSE"'),
        ("lycee", 'nom_de_la_commune="TOULOUSE"'),
    ]

    records = []
    used_uais = set()

    for kind, where in sources:
        print(f"Fetching {kind} IPS data...")
        rows = get(DATASETS[kind], where)
        print(f"{kind} IPS records: {len(rows)}")

        for row in rows:
            uai = first(row, "uai", "UAI")
            if not uai:
                continue
            uai = str(uai)
            d = directory.get(uai)
            if not d:
                # If the national directory has a temporary mismatch, use the
                # IPS row's own name/sector but skip it if coordinates are absent.
                continue

            ips = ips_value(row, kind)
            year = school_year(first(row, "rentree_scolaire", "rentree scolaire", "annee"))
            if not year:
                continue

            # Use the IPS dataset's school type for the record, because an
            # elementary IPS row should remain an elementary point even when
            # the directory has mixed maternelle/elementaire flags.
            name = first(row, "nom_de_l_etablissement", "nom_de_l_etablissment", "Nom_etablissement") or d["name"]
            sector = normalize_sector(first(row, "secteur", "Secteur") or d["sector"])

            records.append({
                "uai": uai,
                "name": name,
                "type": kind,
                "sector": sector,
                "ips": ips,
                "year": year,
                "lat": d["lat"],
                "lon": d["lon"],
            })
            used_uais.add(uai)

    # Add standalone maternelle schools. They do not have an IPS because the
    # official school IPS dataset is based on CM2 pupils, so they get ips=null.
    for uai, d in directory.items():
        if d["type"] == "maternelle":
            records.append({
                "uai": uai,
                "name": d["name"],
                "type": "maternelle",
                "sector": d["sector"],
                "ips": None,
                "year": "",
                "lat": d["lat"],
                "lon": d["lon"],
            })

    # Remove exact duplicates and sort for stable Git commits.
    unique = {}
    for item in records:
        key = (item["uai"], item["type"], item["year"])
        unique[key] = item
    records = list(unique.values())
    records.sort(key=lambda x: (x["type"], x["name"], x["year"], x["uai"]))

    if not records:
        raise RuntimeError("No Toulouse school records were produced. Check the official API field names or dataset availability.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(records)} records to {OUT}")
    print("Years:", sorted({r["year"] for r in records if r["year"]}, reverse=True))


if __name__ == "__main__":
    main()
