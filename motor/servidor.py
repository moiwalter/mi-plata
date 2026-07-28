#!/usr/bin/env python3
"""Servidor local del centro de control de finanzas.

Sirve app.html (el tablero) y expone lo que la app necesita para ESCRIBIR — no sólo
para mirar. Un movimiento sin identificar que sólo se puede resolver editando un JSON
a mano no se resuelve nunca: se acumula y ensucia el tablero. Acá se etiqueta con un toque.

  python3 motor/servidor.py --open     (y abre http://localhost:8765/)

  GET  /                     -> app.html
  GET  /refrescar            -> sync Wallbit + estado nuevo para la app (botón ↻)
  GET  /state[?sync=1]       -> finanzas.py --json (motor); sync=1 refresca Wallbit antes
  GET  /data                 -> data.json (ledger: aportes, checks, gasto cash)
  POST /data                 -> guarda data.json
  POST /label                -> etiqueta una transacción en tx-labels.json (por uuid)
  POST /manual-balances      -> actualiza los saldos que la API no ve

Toda escritura es atómica (temporal + verificación + replace), deja backup del día, y
al terminar REGENERA state.json y lo devuelve — así la app se refresca con el número
ya recalculado por el motor, sin hacer cuentas en el navegador.
"""
import http.server, socketserver, json, os, sys, subprocess, webbrowser, threading
import re
from datetime import date
from urllib.parse import urlparse, parse_qs

# Los datos y la configuración viven en la RAÍZ del repo; el código, en motor/.
DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AQUI = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(DIR, 'data.json')
LABELS = os.path.join(DIR, 'tx-labels.json')
MANUAL = os.path.join(DIR, 'manual-balances.json')
SNAP = os.path.join(DIR, 'wallbit-snapshot.json')
STATE = os.path.join(DIR, 'state.json')
PORT = 8765
PY = sys.executable


def run(args, timeout=120):
    return subprocess.run([PY] + args, cwd=DIR, capture_output=True, text=True, timeout=timeout)


def leer(path, default=None):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def escribir(path, obj):
    """Escritura atómica con backup del día.

    Un archivo de etiquetas a medio escribir es peor que no tenerlo: el motor deja de
    arrancar y el tablero se queda mudo. Se escribe a un temporal, se vuelve a LEER para
    confirmar que quedó JSON válido, y recién ahí reemplaza al original."""
    bak = f'{path}.bak-{date.today().isoformat()}'
    if os.path.exists(path) and not os.path.exists(bak):
        with open(path, 'rb') as s, open(bak, 'wb') as d:
            d.write(s.read())
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    with open(tmp, encoding='utf-8') as f:
        json.load(f)                      # si no parsea, revienta acá y el original queda intacto
    os.replace(tmp, path)


def regenerar():
    """Recalcula state.json con el motor y lo devuelve. La app NO recalcula nada:
    dibuja lo que salió de acá."""
    r = run([os.path.join(AQUI, 'visor-data.py')])
    if r.returncode != 0:
        return None, 'motor: ' + (r.stderr or r.stdout or 'visor-data.py falló')[-500:]
    st = leer(STATE)
    if st is None:
        return None, 'motor: state.json quedó ilegible tras regenerar'
    return st, None



def slug_exc(nombre):
    """Mismo identificador que usa el motor para los gastos ya decididos."""
    t = (nombre or '').lower()
    for a, b in (('á','a'), ('é','e'), ('í','i'), ('ó','o'), ('ú','u'), ('ñ','n')):
        t = t.replace(a, b)
    return re.sub(r'[^a-z0-9]+', '-', t).strip('-')[:40]


def buscar_tx(uuid):
    for t in (leer(SNAP, {}) or {}).get('transactions', []):
        if t.get('uuid') == uuid:
            return t
    return None


def etiquetar(payload):
    """Guarda en tx-labels.json qué fue una transacción. Clave = uuid: la API re-baja las
    transacciones en cada sync sin memoria, así que la verdad vive acá y no se vuelve a
    preguntar nunca por lo mismo."""
    uuid = str(payload.get('uuid') or '').strip()
    if not uuid:
        return None, 'falta el uuid de la transacción'
    tl = leer(LABELS)
    if not isinstance(tl, dict):
        return None, 'no pude leer tx-labels.json'
    tl.setdefault('labels', {})

    if payload.get('accion') == 'borrar':          # deshacer una etiqueta recién puesta
        tl['labels'].pop(uuid, None)
        tl['updated'] = date.today().isoformat()
        escribir(LABELS, tl)
        return regenerar()

    if payload.get('accion') == 'describir':
        # DESCRIBIR ≠ CLASIFICAR. Sólo el dueño sabe QUÉ fue un movimiento; meterlo en la
        # taxonomía es mecánico y lo puede hacer el agente después. Obligarlo a elegir
        # categoría en el momento hacía que escribiera la nota y se perdiera al redibujar.
        # La descripción se guarda sola y el movimiento SIGUE en la cola, ahora con contexto.
        texto = str(payload.get('nota') or '').strip()
        tl.setdefault('descripciones', {})
        if texto:
            tl['descripciones'][uuid] = {'texto': texto[:200],
                                         'fecha': date.today().isoformat(),
                                         'clasificado': False}
        else:
            tl['descripciones'].pop(uuid, None)
        tl['updated'] = date.today().isoformat()
        escribir(LABELS, tl)
        return regenerar()

    cat = str(payload.get('cat') or '').strip()
    validas = [k for k in tl.get('_categories', {}) if not k.startswith('_')]
    if cat not in validas:
        return None, f'categoría desconocida: {cat!r}. Las válidas viven en tx-labels.json → _categories'

    tx = buscar_tx(uuid)
    if tx is None:
        return None, 'esa transacción no está en el snapshot de Wallbit'

    entrada = {'label': str(payload.get('label') or payload.get('nota') or cat)[:80], 'cat': cat}
    # Un cargo de tarjeta liquida en USD y un QR en Bs. Guardar el monto en la moneda en
    # que ocurrió evita que una tasa futura reescriba el pasado.
    dest = ((tx.get('dest_currency') or {}).get('code') or '').upper()
    if dest == 'BOB':
        entrada['monto_bs'] = round(float(tx.get('dest_amount') or 0), 2)
    else:
        entrada['monto_usd'] = round(float(tx.get('source_amount') or 0), 2)
    entrada['fecha'] = str(payload.get('fecha') or (tx.get('created_at') or '')[:10])
    # A qué gasto ya decidido pertenece (el pasaje del viaje, la cena del cumpleaños).
    # Sin esto, pagar parte de un excepcional bajaba la caja Y seguía reservando el monto
    # entero: la misma plata contada dos veces.
    exc = str(payload.get('excepcional') or '').strip()
    if exc:
        plan = leer(os.path.join(DIR, 'plan.json'), {}) or {}
        ids = {(i.get('id') or slug_exc(i.get('nombre'))): i
               for i in ((plan.get('budget') or {}).get('excepcionales') or {}).get('items', [])}
        if exc not in ids:
            return None, f'no existe el gasto decidido {exc!r}. Los que hay: {", ".join(ids) or "ninguno"}'
        entrada['excepcional'] = exc

    nota = str(payload.get('nota') or '').strip()
    # Si ya habías descrito el movimiento con tus palabras, esa descripción ES la nota:
    # se absorbe al clasificar y deja de estar pendiente. Si no, quedaría colgada para
    # siempre en `descripciones` y la lista de "falta clasificar" nunca se vaciaría.
    desc = (tl.get('descripciones', {}) or {}).pop(uuid, None)
    if not nota and desc:
        nota = str(desc.get('texto') or '').strip()
    if nota:
        entrada['nota'] = nota[:200]

    tl['labels'][uuid] = entrada
    tl['updated'] = date.today().isoformat()
    escribir(LABELS, tl)
    return regenerar()


def saldos_manuales(payload):
    """Actualiza los saldos que la API de Wallbit no ve (exchange, banco local).
    Sólo toca el monto: las notas y la estructura del archivo se respetan tal cual."""
    cuentas = payload.get('accounts')
    if not isinstance(cuentas, list) or not cuentas:
        return None, 'no mandaste ninguna cuenta'
    mb = leer(MANUAL)
    if not isinstance(mb, dict) or not isinstance(mb.get('accounts'), list):
        return None, 'no pude leer manual-balances.json'
    porNombre = {a.get('name'): a for a in mb['accounts']}
    tocadas = 0
    for c in cuentas:
        a = porNombre.get(c.get('name'))
        if a is None:
            return None, f'no existe la cuenta {c.get("name")!r} en manual-balances.json'
        try:
            monto = float(c.get('amount'))
        except (TypeError, ValueError):
            return None, f'monto inválido para {c.get("name")!r}'
        if monto < 0:
            return None, f'{c.get("name")}: un saldo no puede ser negativo'
        if abs(monto - float(a.get('amount', 0) or 0)) < 1e-9:
            continue
        a['amount'] = monto
        a['actualizado'] = date.today().isoformat()   # de dónde salió el número y cuándo
        if c.get('note'):
            a['note'] = str(c['note'])[:300]
        tocadas += 1
    if not tocadas:
        st = leer(STATE)
        return (st, None) if st else (None, 'nada que cambiar y no hay state.json')
    mb['updated'] = date.today().isoformat()
    escribir(MANUAL, mb)
    return regenerar()


class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=DIR, **k)

    def end_headers(self):
        """Nada de este servidor se cachea — ni la app, ni los datos.

        `_send` ya mandaba no-store, pero SÓLO para las respuestas de la API. Los
        archivos estáticos (app.html) los sirve la clase padre, que no manda ninguna
        cabecera de caché: el navegador entonces decide por su cuenta con Last-Modified
        y se queda con la versión vieja. Resultado: cambiabas la app, recargabas, y
        seguías viendo la anterior sin entender por qué. Va acá, en end_headers, porque
        es el único punto por el que pasan TODAS las respuestas.
        """
        if not any(h.lower() == 'cache-control' for h, _ in self._headers_buffer_names()):
            self.send_header('Cache-Control', 'no-store, must-revalidate')
        super().end_headers()

    def _headers_buffer_names(self):
        out = []
        for raw in (self._headers_buffer or [])[1:]:
            try:
                linea = raw.decode('latin-1').strip()
            except Exception:
                continue
            if ':' in linea:
                k, v = linea.split(':', 1)
                out.append((k.strip(), v.strip()))
        return out

    def _send(self, code, body, ctype='application/json'):
        b = body.encode('utf-8') if isinstance(body, str) else body
        self.send_response(code)
        # El charset va SIEMPRE en la cabecera: sin él el navegador adivina, cae a
        # Latin-1 y parte cada acento en dos ("mayoría" → "mayorÃ­a"). El <meta> del
        # HTML también lo declara, pero la cabecera manda y no depende de que el
        # archivo se sirva entero.
        if 'charset' not in ctype:
            ctype += '; charset=utf-8'
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(b)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(b)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def _cuerpo(self):
        n = int(self.headers.get('Content-Length', 0) or 0)
        return json.loads(self.rfile.read(n) or b'{}')

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == '/refrescar':
            # El botón ↻ del tablero. `/state` devuelve el JSON del MOTOR (para agentes y
            # scripts); la app dibuja otra forma, la de visor-data. Mezclarlos dejaba la
            # pantalla en blanco, así que el refresco de la app tiene su propia puerta:
            # trae lo nuevo de Wallbit, regenera el estado y devuelve lo que la app entiende.
            try:
                run([os.path.join(AQUI, 'wallbit-sync.py'), '--days', '35'])
                st, err = regenerar()
                if err:
                    self._json(500, {'error': err})
                    return
                self._json(200, st)
            except Exception as e:
                self._json(500, {'error': str(e)})
            return
        if u.path == '/state':
            q = parse_qs(u.query)
            try:
                if q.get('sync', ['0'])[0] == '1':
                    run([os.path.join(AQUI, 'wallbit-sync.py'), '--days', '35'])
                r = run([os.path.join(AQUI, 'finanzas.py'), '--json'])
                if r.returncode != 0:
                    self._json(500, {'error': r.stderr[-400:]})
                    return
                self._send(200, r.stdout)
            except Exception as e:
                self._json(500, {'error': str(e)})
            return
        if u.path == '/data':
            try:
                b = open(DATA, 'rb').read()
            except Exception:
                b = b'{}'
            self._send(200, b)
            return
        if u.path in ('/', ''):
            self.path = '/app.html'
        return super().do_GET()

    def do_POST(self):
        ruta = urlparse(self.path).path
        if ruta == '/data':
            n = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(n)
            try:
                json.loads(body)
                with open(DATA, 'wb') as f:
                    f.write(body)
                self.send_response(204)
                self.end_headers()
            except Exception:
                self.send_response(400)
                self.end_headers()
            return

        if ruta in ('/label', '/manual-balances'):
            try:
                payload = self._cuerpo()
            except Exception:
                self._json(400, {'error': 'el cuerpo no es JSON válido'})
                return
            try:
                estado, err = (etiquetar if ruta == '/label' else saldos_manuales)(payload)
            except Exception as e:
                self._json(500, {'error': f'{type(e).__name__}: {e}'})
                return
            if err:
                # 400 = lo que mandó la app está mal · 500 = el motor no pudo recalcular
                self._json(500 if err.startswith('motor:') else 400, {'error': err})
                return
            self._json(200, estado)
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, *a):
        pass


class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


if __name__ == '__main__':
    if '--open' in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(f'http://localhost:{PORT}/')).start()
    print(f'\n  Finanzas → http://localhost:{PORT}/')
    print('  /state?sync=1 refresca Wallbit · POST /label etiqueta · POST /manual-balances actualiza saldos\n')
    try:
        Server(('127.0.0.1', PORT), H).serve_forever()
    except KeyboardInterrupt:
        print('Detenido.')
