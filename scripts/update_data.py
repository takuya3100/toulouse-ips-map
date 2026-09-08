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


def get(dataset, refine=None):
    all_results = []
    offset = 0
    limit = 100

    while True:
        params = {
            "limit": limit,
            "offset": offset
        }

        if refine:
            params["refine"] = refine

        query = urllib.parse.urlencode(params)

        url = BASE + dataset + "/records?" + query

        print(f"GET {url}")

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "toulouse-ips-map/1.0"
            }
        )

        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.load(r)

        results = payload.get("results", [])
        all_results.extend(results)

        print(
            f"  received {len(results)} records "
            f"(total so far: {len(all_results)})"
        )

        if len(results) < limit:
            break

        offset += limit

    return all_results


def first(row, *names):
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def truthy(value):
    if isinstance(value, bool):
        return value

    return str(value or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "oui",
        "y"
    }


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

    if len(text) >= 4 and text[:4].isdigit():
        return text[:4]

    return text


def normalize_sector(value):
    text = str(value or "").strip().lower()

    if "priv" in text:
        return "Privé"

    return "Public"


def infer_type(row):

    if (
        truthy(row.get("ecole_maternelle"))
        and not truthy(row.get("ecole_elementaire"))
    ):
        return "maternelle"

    if truthy(row.get("ecole_elementaire")):
        return "elementaire"

    type_etab = str(
        row.get("type_etablissement") or ""
    ).strip().lower()

    if "coll" in type_etab:
        return "college"

    if any(
        truthy(row.get(key))
        for key in (
            "voie_generale",
            "voie_technologique",
            "voie_professionnelle"
        )
    ):
        return "lycee"

    nature = str(
        row.get("libelle_nature") or ""
    ).lower()

    if "collège" in nature or "college" in nature:
        return "college"

    if "lycée" in nature or "lycee" in nature:
        return "lycee"

    if "maternelle" in nature:
        return "maternelle"

    if "élémentaire" in nature or "elementaire" in nature:
        return "elementaire"

    return None


def get_ips(row, kind):

    if kind == "elementaire":
        return to_float(
            first(row, "ips")
        )

    if kind == "college":
        return to_float(
            first(
                row,
                "ips",
                "ips_etablissement"
            )
        )

    if kind == "lycee":
        return to_float(
            first(
                row,
                "ips_de_l_etablissement",
                "ips_etab",
                "ips_ensemble_gt_pro"
            )
        )

    return None


def main():

    print("Fetching Toulouse school directory...")

    # 現在の公式APIでは nom_commune は小文字
    directory_rows = get(
        DATASETS["directory"],
        "nom_commune:TOULOUSE"
    )

    print(
        f"Directory records: {len(directory_rows)}"
    )

    directory = {}

    for row in directory_rows:

        uai = first(
            row,
            "identifiant_de_l_etablissement",
            "uai"
        )

        lat = to_float(
            first(
                row,
                "latitude"
            )
        )

        lon = to_float(
            first(
                row,
                "longitude"
            )
        )

        if not uai or lat is None or lon is None:
            continue

        directory[str(uai)] = {
            "uai": str(uai),

            "name": first(
                row,
                "nom_etablissement"
            ) or "",

            "sector": normalize_sector(
                first(
                    row,
                    "statut_public_prive"
                )
            ),

            "type": infer_type(row),

            "lat": lat,
            "lon": lon
        }

    records = []

    sources = [
        (
            "elementaire",
            "nom_de_la_commune:TOULOUSE"
        ),
        (
            "college",
            "nom_de_la_commune:TOULOUSE"
        ),
        (
            "lycee",
            "nom_de_la_commune:TOULOUSE"
        )
    ]

    for kind, refine in sources:

        print(
            f"Fetching {kind} IPS data..."
        )

        rows = get(
            DATASETS[kind],
            refine
        )

        print(
            f"{kind} IPS records: {len(rows)}"
        )

        for row in rows:

            uai = first(
                row,
                "uai"
            )

            if not uai:
                continue

            uai = str(uai)

            school = directory.get(uai)

            if not school:
                continue

            ips = get_ips(
                row,
                kind
            )

            year = school_year(
                first(
                    row,
                    "rentree_scolaire",
                    "rentree scolaire"
                )
            )

            if not year:
                continue

            name = first(
                row,
                "nom_de_l_etablissement",
                "nom_de_l_etablissment"
            ) or school["name"]

            sector = normalize_sector(
                first(
                    row,
                    "secteur"
                ) or school["sector"]
            )

            records.append({
                "uai": uai,
                "name": name,
                "type": kind,
                "sector": sector,
                "ips": ips,
                "year": year,
                "lat": school["lat"],
                "lon": school["lon"]
            })

    # Maternelle
    for uai, school in directory.items():

        if school["type"] != "maternelle":
            continue

        records.append({
            "uai": uai,
            "name": school["name"],
            "type": "maternelle",
            "sector": school["sector"],
            "ips": None,
            "year": "",
            "lat": school["lat"],
            "lon": school["lon"]
        })

    # 重複削除
    unique = {}

    for item in records:

        key = (
            item["uai"],
            item["type"],
            item["year"]
        )

        unique[key] = item

    records = list(
        unique.values()
    )

    records.sort(
        key=lambda x: (
            x["type"],
            x["name"],
            x["year"],
            x["uai"]
        )
    )

    if not records:
        raise RuntimeError(
            "No Toulouse school records were produced."
        )

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    OUT.write_text(
        json.dumps(
            records,
            ensure_ascii=False,
            indent=2
        ) + "\n",
        encoding="utf-8"
    )

    print(
        f"Wrote {len(records)} records to {OUT}"
    )

    print(
        "Years:",
        sorted(
            {
                r["year"]
                for r in records
                if r["year"]
            },
            reverse=True
        )
    )


if __name__ == "__main__":
    main()
