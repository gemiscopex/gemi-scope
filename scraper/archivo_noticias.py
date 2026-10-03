"""
SCOPE — Archivo histórico de noticias (append-only).

noticias.json guarda solo las ~600 notas más recientes (unas dos semanas) y
noticias-estatales.json una ventana de 7 días: lo que sale de la ventana se pierde.
Este paso corre después de los scrapers y copia cada nota a un archivo mensual
que nunca se recorta:

  data/noticias-historico/AAAA-MM.json   notas de ese mes (por fecha de publicación)
  data/noticias-historico/indice.json    conteo por mes y por ámbito (nacional / estatal)

Una nota se identifica por su URL normalizada (sin parámetros); si ya existe se
completan sus campos, nunca se borra. `visto_primero` registra cuándo la detectó Scope.
El campo `empresas` (capa privada de la terminal por empresa) no se archiva.
Costo $0: sin IA, sin base de datos.
"""
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / 'data'
DIR = DATA / 'noticias-historico'
FUENTES = (('noticias.json', 'nacional'), ('noticias-estatales.json', 'estatal'))
CAMPOS = ('titulo', 'url', 'fuente', 'autoridad', 'resumen', 'categoria', 'categoria_nombre', 'categorias', 'estado')


def ahora_cdmx():
    return datetime.now(timezone(timedelta(hours=-6))).strftime('%Y-%m-%dT%H:%M:%S-06:00')


def items_de(d):
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for k in ('items', 'noticias', 'data'):
            if isinstance(d.get(k), list):
                return d[k]
    return []


def clave(x):
    u = re.sub(r'[?#].*$', '', (x.get('url') or x.get('link') or '').strip()).rstrip('/').lower()
    return u or x.get('id') or hashlib.md5((x.get('titulo') or '').encode()).hexdigest()


def fecha_de(x):
    for k in ('fecha_publicacion', 'fecha', 'published', 'date'):
        m = re.match(r'(\d{4}-\d{2}-\d{2})', str(x.get(k) or ''))
        if m:
            return m.group(1)
    return ''


def cargar(p):
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except Exception:
        return None


def main():
    DIR.mkdir(parents=True, exist_ok=True)
    visto = ahora_cdmx()
    meses = {}                      # 'AAAA-MM' -> {clave: nota}

    def mes(m):
        if m not in meses:
            prev = cargar(DIR / f'{m}.json') or []
            meses[m] = {clave(r): r for r in prev}
        return meses[m]

    nuevas = 0
    for nombre, ambito in FUENTES:
        for x in items_de(cargar(DATA / nombre)):
            if not isinstance(x, dict) or not x.get('titulo'):
                continue
            f = fecha_de(x) or visto[:10]
            k = clave(x)
            bucket = mes(f[:7])
            r = bucket.get(k)
            if r is None:
                r = {'id': x.get('id') or hashlib.md5(k.encode()).hexdigest()[:12], 'ambito': ambito, 'visto_primero': visto}
                bucket[k] = r
                nuevas += 1
            for c in CAMPOS:
                v = x.get(c)
                if v not in (None, '', []):
                    r[c] = v
            r['fecha'] = f

    for m, bucket in meses.items():
        notas = sorted(bucket.values(), key=lambda r: (r.get('fecha', ''), r.get('visto_primero', '')), reverse=True)
        (DIR / f'{m}.json').write_text(json.dumps(notas, ensure_ascii=False, indent=0), encoding='utf-8')

    # índice: recuenta todos los meses en disco
    indice = {'_meta': {'actualizado': visto, 'nota': 'Archivo acumulado de noticias (nacional y estatal). Append-only: no se descarta por antigüedad.'},
              'meses': {}}
    total = 0
    for p in sorted(DIR.glob('????-??.json')):
        notas = cargar(p) or []
        n = {'nacional': 0, 'estatal': 0}
        for r in notas:
            n[r.get('ambito', 'nacional')] = n.get(r.get('ambito', 'nacional'), 0) + 1
        indice['meses'][p.stem] = {'total': len(notas), **n}
        total += len(notas)
    indice['_meta']['total'] = total
    (DIR / 'indice.json').write_text(json.dumps(indice, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'  archivo de noticias: {nuevas} nuevas · {total} en total · {len(indice["meses"])} meses')


if __name__ == '__main__':
    main()
