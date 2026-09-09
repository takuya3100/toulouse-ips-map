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


# Toulouse Métropole の公式37自治体
# INSEEコード : 自治体名
METROPOLE = {
    "31003": "Aigrefeuille",
    "31022": "Aucamville",
    "31032": "Aussonne",
    "31044": "Balma",
    "31053": "Beaupuy",
    "31056": "Beauzelle",
    "31069": "Blagnac",
    "31088": "Brax",
    "31091": "Bruguières",
    "31116": "Castelginest",
    "31149": "Colomiers",
    "31150": "Cornebarrieu",
    "31157": "Cugnaux",
    "31163": "Drémil-Lafage",
    "31182": "Fenouillet",
    "31184": "Flourens",
    "31186": "Fonbeauzard",
    "31205": "Gagnac-sur-Garonne",
    "31230": "Gratentour",
    "31282": "Launaguet",
    "31293": "Lespinasse",
    "31351": "Mondonville",
    "31352": "Mondouzil",
    "31355": "Mons",
    "31389": "Montrabé",
    "31417": "Pibrac",
    "31418": "Pin-Balma",
    "31445": "Quint-Fonsegrives",
    "31467": "Saint-Alban",
    "31488": "Saint-Jean",
    "31490": "Saint-Jory",
    "31506": "Saint-Orens-de-Gameville",
    "31541": "Seilh",
    "31555": "Toulouse",
    "31557": "Tournefeuille",
    "31561": "L'Union",
    "31588": "Villeneuve-Tolosane",
}


def validate_metropole():
    """
    Toulouse Métropole の自治体リストが正しいか確認する。
    """
    if len(METROPOLE) != 37:
        raise RuntimeError(
            f"Toulouse Métropole の自治体数が37ではありません: {len(METROPOLE)}"
        )

    if len(set(METROPOLE.keys())) != 37:
        raise RuntimeError("INSEEコードに重複があります。")

    if len(set(METROPOLE.values())) != 37:
        raise RuntimeError("自治体名に重複があります。")

    print("")
    print("Toulouse Métropole: 37 communes")
    print("--------------------------------")

    for code, name in METROPOLE.items():
        print(f"{code}  {name}")

    print("")


def get(dataset, where=None):
    """
    Opendatasoft Explore API から全ページ取得する。
    """
    all_results = []
    offset = 0
    limit = 100

    while True:
        params = {
            "limit": limit,
            "offset": offset,
        }

        if where:
            params["where"] = where

        query = urllib.parse.urlencode(params)
        url = BASE + dataset + "/records?" + query

        print(f"GET {url}")

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "toulouse-ips-map/1.0"
            },
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
    """
    複数候補のフィールド名から最初に値が入っているものを取得。
    """
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
        "y",
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

    return str(value).strip()


def normalize_sector(value):
    text = str(value or "").strip().lower()

    if "priv" in text:
        return "Privé"

    return "Public"


def infer_type(row):
    """
    教育機関ディレクトリから学校種別を判定する。
    """

    # 幼稚園
    if truthy(row.get("ecole_maternelle")) and not truthy(
        row.get("ecole_elementaire")
    ):
        return "maternelle"

    # 小学校
    if truthy(row.get("ecole_elementaire")):
        return "elementaire"

    # 中学校
    type_etab = str(
        row.get("type_etablissement") or ""
    ).strip().lower()

    if "coll" in type_etab:
        return "college"

    # 高校
    if any(
        truthy(row.get(key))
        for key in (
            "voie_generale",
            "voie_technologique",
            "voie_professionnelle",
        )
    ):
        return "lycee"

    # libelle_nature を使った補完
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
    """
    学校種別ごとにIPSを取得。
    """

    if kind == "elementaire":
        return to_float(
            first(
                row,
                "ips",
            )
        )

    if kind == "college":
        return to_float(
            first(
                row,
                "ips",
                "ips_etablissement",
            )
        )

    if kind == "lycee":
        return to_float(
            first(
                row,
                "ips_de_l_etablissement",
                "ips_etab",
                "ips_ensemble_gt_pro",
            )
        )

    return None


def main():

    validate_metropole()

    codes = list(METROPOLE.keys())

    code_list = ",".join(
        f"'{code}'"
        for code in codes
    )

    # --------------------------------------------------
    # 1. 学校ディレクトリ
    # --------------------------------------------------

    directory_where = (
        f"code_commune IN ({code_list})"
    )

    print("")
    print("========================================")
    print("Fetching Toulouse Métropole school directory")
    print("========================================")

    directory_rows = get(
        DATASETS["directory"],
        directory_where,
    )

    print(
        f"Directory records: {len(directory_rows)}"
    )

    directory = {}

    duplicate_uai = set()

    directory_municipalities = set()

    directory_type_counts = {}

    for row in directory_rows:

        uai = first(
            row,
            "identifiant_de_l_etablissement",
            "uai",
        )

        lat = to_float(
            first(row, "latitude")
        )

        lon = to_float(
            first(row, "longitude")
        )

        code_commune = first(
            row,
            "code_commune",
            "code_insee_de_la_commune",
        )

        if not uai:
            continue

        if code_commune not in METROPOLE:
            continue

        if lat is None or lon is None:
            continue

        uai = str(uai)

        if uai in directory:
            duplicate_uai.add(uai)

        school_type = infer_type(row)

        if school_type is None:
            continue

        municipality_name = METROPOLE[code_commune]

        directory_municipalities.add(
            code_commune
        )

        directory_type_counts[school_type] = (
            directory_type_counts.get(school_type, 0) + 1
        )

        directory[uai] = {
            "uai": uai,
            "name": first(
                row,
                "nom_etablissement",
            ) or "",
            "sector": normalize_sector(
                first(
                    row,
                    "statut_public_prive",
                )
            ),
            "type": school_type,
            "commune_code": code_commune,
            "commune": municipality_name,
            "lat": lat,
            "lon": lon,
        }

    print("")
    print("Directory school types:")
    for school_type, count in sorted(
        directory_type_counts.items()
    ):
        print(f"  {school_type}: {count}")

    if duplicate_uai:
        print("")
        print(
            "WARNING: duplicate UAI found:",
            len(duplicate_uai),
        )

    missing_directory = (
        set(METROPOLE.keys())
        - directory_municipalities
    )

    if missing_directory:
        print("")
        print(
            "WARNING: municipalities with no "
            "recognized school directory records:"
        )

        for code in sorted(missing_directory):
            print(
                f"  {code}  {METROPOLE[code]}"
            )

    else:
        print("")
        print(
            "All 37 municipalities have "
            "recognized school directory records."
        )

    # --------------------------------------------------
    # 2. IPSデータ
    # --------------------------------------------------

    records = []

    sources = [
        (
            "elementaire",
            "code_insee_de_la_commune",
        ),
        (
            "college",
            "code_insee_de_la_commune",
        ),
        (
            "lycee",
            "code_insee_de_la_commune",
        ),
    ]

    ips_stats = {}

    unmatched_uai = {}

    for kind, field_name in sources:

        where = (
            f"{field_name} IN ({code_list})"
        )

        print("")
        print("========================================")
        print(
            f"Fetching {kind} IPS data"
        )
        print("========================================")

        rows = get(
            DATASETS[kind],
            where,
        )

        print(
            f"{kind} IPS records: {len(rows)}"
        )

        matched = 0
        unmatched = 0

        years = set()

        for row in rows:

            uai = first(
                row,
                "uai",
            )

            if not uai:
                continue

            uai = str(uai)

            school = directory.get(uai)

            if not school:
                unmatched += 1
                continue

            ips = get_ips(
                row,
                kind,
            )

            year = school_year(
                first(
                    row,
                    "rentree_scolaire",
                    "rentree scolaire",
                )
            )

            if not year:
                continue

            years.add(year)

            name = (
                first(
                    row,
                    "nom_de_l_etablissement",
                    "nom_de_l_etablissment",
                )
                or school["name"]
            )

            sector = normalize_sector(
                first(
                    row,
                    "secteur",
                )
                or school["sector"]
            )

            records.append(
                {
                    "uai": uai,
                    "name": name,
                    "type": kind,
                    "sector": sector,
                    "commune_code": school[
                        "commune_code"
                    ],
                    "commune": school[
                        "commune"
                    ],
                    "ips": ips,
                    "year": year,
                    "lat": school["lat"],
                    "lon": school["lon"],
                }
            )

            matched += 1

        ips_stats[kind] = {
            "rows": len(rows),
            "matched": matched,
            "unmatched": unmatched,
            "years": sorted(
                years,
                reverse=True,
            ),
        }

        unmatched_uai[kind] = unmatched

    # --------------------------------------------------
    # 3. 幼稚園を追加
    # --------------------------------------------------

    kindergarten_count = 0

    for uai, school in directory.items():

        if school["type"] != "maternelle":
            continue

        records.append(
            {
                "uai": uai,
                "name": school["name"],
                "type": "maternelle",
                "sector": school["sector"],
                "commune_code": school[
                    "commune_code"
                ],
                "commune": school[
                    "commune"
                ],
                "ips": None,
                "year": "",
                "lat": school["lat"],
                "lon": school["lon"],
            }
        )

        kindergarten_count += 1

    print("")
    print(
        f"Kindergarten records added: "
        f"{kindergarten_count}"
    )

    # --------------------------------------------------
    # 4. 重複排除
    # --------------------------------------------------

    unique = {}

    for item in records:

        key = (
            item["uai"],
            item["type"],
            item["year"],
        )

        unique[key] = item

    records = list(
        unique.values()
    )

    records.sort(
        key=lambda x: (
            x["commune"],
            x["type"],
            x["name"],
            x["year"],
            x["uai"],
        )
    )

    # --------------------------------------------------
    # 5. 最終データ検証
    # --------------------------------------------------

    if not records:
        raise RuntimeError(
            "No Toulouse Métropole school "
            "records were produced."
        )

    outside_scope = [
        r
        for r in records
        if r["commune_code"]
        not in METROPOLE
    ]

    if outside_scope:
        raise RuntimeError(
            "Records from outside Toulouse "
            f"Métropole were found: "
            f"{len(outside_scope)}"
        )

    # 自治体別件数
    municipality_counts = {}

    for record in records:

        code = record["commune_code"]

        municipality_counts[code] = (
            municipality_counts.get(code, 0) + 1
        )

    # 学校種別件数
    type_counts = {}

    for record in records:

        school_type = record["type"]

        type_counts[school_type] = (
            type_counts.get(school_type, 0) + 1
        )

    # 年度
    years = sorted(
        {
            r["year"]
            for r in records
            if r["year"]
        },
        reverse=True,
    )

    # --------------------------------------------------
    # 6. ログ出力
    # --------------------------------------------------

    print("")
    print("========================================")
    print("IPS matching summary")
    print("========================================")

    for kind, stats in ips_stats.items():

        print(
            f"{kind}: "
            f"source={stats['rows']}, "
            f"matched={stats['matched']}, "
            f"unmatched={stats['unmatched']}"
        )

        print(
            "  years:",
            stats["years"],
        )

    print("")
    print("========================================")
    print("Final school type counts")
    print("========================================")

    for school_type, count in sorted(
        type_counts.items()
    ):
        print(
            f"  {school_type}: {count}"
        )

    print("")
    print("========================================")
    print("Final municipality counts")
    print("========================================")

    for code in sorted(
        METROPOLE.keys(),
        key=lambda x: METROPOLE[x],
    ):

        name = METROPOLE[code]

        print(
            f"  {name}: "
            f"{municipality_counts.get(code, 0)}"
        )

    print("")
    print("========================================")
    print("Years")
    print("========================================")

    print(years)

    # --------------------------------------------------
    # 7. JSON書き出し
    # --------------------------------------------------

    OUT.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    OUT.write_text(
        json.dumps(
            records,
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print("")
    print(
        f"Wrote {len(records)} records to {OUT}"
    )


if __name__ == "__main__":
    main()
