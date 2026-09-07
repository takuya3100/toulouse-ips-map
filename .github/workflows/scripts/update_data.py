import json, urllib.parse, urllib.request
from pathlib import Path

BASE='https://data.education.gouv.fr/api/explore/v2.1/catalog/datasets/'
DATASETS={
 'directory':'fr-en-annuaire-education',
 'elementaire':'fr-en-ips-ecoles-ap2022',
 'college':'fr-en-ips-colleges-ap2023',
 'lycee':'fr-en-ips-lycees-ap2023',
}
OUT=Path(__file__).resolve().parents[1]/'data'/'schools.json'

def get(ds, where):
    params=urllib.parse.urlencode({'where':where,'limit':10000})
    with urllib.request.urlopen(BASE+ds+'/records?'+params, timeout=60) as r:
        return json.load(r).get('results',[])

def val(row,*names):
    for n in names:
        if n in row and row[n] not in (None,''): return row[n]
    return None

def year(v):
    if v is None:return ''
    return str(v).split('-')[0]

def main():
    directory=get(DATASETS['directory'],'nom_commune="TOULOUSE"')
    by_uai={str(val(r,'UAI','uai')):r for r in directory if val(r,'UAI','uai')}
    out={}
    for kind,ds in [('elementaire',DATASETS['elementaire']),('college',DATASETS['college']),('lycee',DATASETS['lycee'])]:
        rows=get(ds,'nom_de_la_commune="TOULOUSE"')
        for r in rows:
            u=str(val(r,'uai','UAI') or '')
            if not u: continue
            d=by_uai.get(u,{})
            lat=val(d,'latitude','Latitude'); lon=val(d,'longitude','Longitude')
            if lat is None or lon is None: continue
            y=year(val(r,'rentree_scolaire','rentree scolaire'))
            ips=val(r,'ips','ips_de_l_etablissement','IPS_de_l_etablissement')
            try: ips=float(ips) if ips is not None else None
            except: ips=None
            out[(u,y,kind)]={
              'uai':u,'name':val(r,'nom_de_l_etablissement','nom_de_l_etablissment','Nom_etablissement') or val(d,'Nom_etablissement') or '',
              'type':kind,'sector':val(r,'secteur','Secteur') or val(d,'Code_type_etablissement') or 'Public',
              'ips':ips,'year':y,'lat':float(lat),'lon':float(lon)
            }
    # Maternelles: directory entries whose nature/type contains maternelle; no IPS.
    for u,d in by_uai.items():
        nature=' '.join(str(val(d,k) or '') for k in ['Libelle_nature','libelle_nature','type_etablissement','Type_etablissement']).lower()
        name=str(val(d,'Nom_etablissement','nom_etablissement') or '')
        if 'maternelle' not in nature and 'maternelle' not in name.lower(): continue
        lat=val(d,'latitude','Latitude');lon=val(d,'longitude','Longitude')
        if lat is None or lon is None:continue
        out[(u,'directory','maternelle')]={'uai':u,'name':name,'type':'maternelle','sector':'Privé' if 'priv' in str(val(d,'Code_type_contrat_prive','secteur') or '').lower() else 'Public','ips':None,'year':'directory','lat':float(lat),'lon':float(lon)}
    rows=list(out.values())
    rows.sort(key=lambda x:(x['type'],x['name'],x['year']))
    OUT.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'wrote {len(rows)} rows to {OUT}')

if __name__=='__main__': main()
