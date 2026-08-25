/**
 * SCOPE — Backend de notas y comentarios (Google Apps Script → Google Sheet)
 *
 * Sirve para NOMs, iniciativas del Congreso y cualquier elemento con id.
 * Guarda cada comentario en la hoja, avisa por correo a SCOPE y devuelve
 * los comentarios (texto) para pintarlos en el sitio, no solo el conteo.
 *
 * CÓMO DESPLEGARLO
 * 1. Crea una Google Sheet nueva con la cuenta gemiscopex@gmail.com.
 * 2. Menú: Extensiones → Apps Script. Borra lo que haya y pega TODO este archivo.
 * 3. Guarda. Luego: Implementar → Nueva implementación → tipo "Aplicación web".
 *      - Ejecutar como:  Yo (gemiscopex@gmail.com)
 *      - Quién tiene acceso:  Cualquier persona
 * 4. Copia la URL que termina en /exec y pásasela a Claude
 *    (o pégala tú en index.html, en la variable SCOPE_COMMENTS_ENDPOINT).
 * 5. Si vuelves a editar este archivo, usa "Implementar → Gestionar
 *    implementaciones → editar (lápiz) → Nueva versión" para que el cambio
 *    entre en vigor SIN cambiar la URL.
 */

var SHEET_NAME   = 'comentarios';
var NOTIFY_EMAIL = 'gemiscopex@gmail.com';   // pon '' si no quieres correo por comentario
var MAX_TXT      = 4000;
var MAX_META     = 160;

function _sheet() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sh = ss.getSheetByName(SHEET_NAME);
  if (!sh) {
    sh = ss.insertSheet(SHEET_NAME);
    sh.appendRow(['fecha', 'id', 'tipo', 'nombre', 'email', 'comentario']);
  }
  // Migración suave: si la hoja vieja no tiene la columna 'tipo', se sigue leyendo bien.
  return sh;
}

function _json(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}

// Detecta el índice de columnas por encabezado (tolera la hoja vieja sin 'tipo').
function _cols(rows) {
  var head = (rows[0] || []).map(function (h) { return String(h || '').toLowerCase(); });
  function idx(name, def) { var i = head.indexOf(name); return i >= 0 ? i : def; }
  return {
    fecha: idx('fecha', 0),
    id:    head.indexOf('id') >= 0 ? head.indexOf('id') : idx('nom', 1),
    tipo:  head.indexOf('tipo') >= 0 ? head.indexOf('tipo') : -1,
    nombre: head.indexOf('tipo') >= 0 ? idx('nombre', 3) : idx('nombre', 2),
    coment: idx('comentario', head.indexOf('tipo') >= 0 ? 5 : 4)
  };
}

/**
 * GET:
 *   ?action=all      → { id: [ {n, t, ts}, ... ], ... }   (default; comentarios por id, recientes primero)
 *   ?action=counts   → { id: n, ... }
 *   ?action=list&id= → [ {n, t, ts}, ... ]
 */
function doGet(e) {
  var p = (e && e.parameter) || {};
  var action = p.action || 'all';
  var sh = _sheet();
  var rows = sh.getDataRange().getValues();
  var c = _cols(rows);

  if (action === 'counts') {
    var counts = {};
    for (var i = 1; i < rows.length; i++) {
      var id = rows[i][c.id];
      if (id) counts[id] = (counts[id] || 0) + 1;
    }
    return _json(counts);
  }

  var wantId = (p.id || p.nom || '').toString();
  var byId = {};
  for (var j = 1; j < rows.length; j++) {
    var rid = rows[j][c.id];
    if (!rid) continue;
    if (action === 'list' && String(rid) !== wantId) continue;
    var rec = {
      n:  String(rows[j][c.nombre] || ''),
      t:  String(rows[j][c.coment] || ''),
      ts: (function (v) { var d = new Date(v); return isNaN(d) ? 0 : d.getTime(); })(rows[j][c.fecha])
    };
    (byId[rid] = byId[rid] || []).push(rec);
  }
  // Recientes primero
  Object.keys(byId).forEach(function (k) { byId[k].sort(function (a, b) { return b.ts - a.ts; }); });

  if (action === 'list') return _json(byId[wantId] || []);
  return _json(byId);
}

// POST (form-encoded: id|nom, tipo, nombre, email, comentario) → { ok, comment }
function doPost(e) {
  var p = (e && e.parameter) || {};
  var id = (p.id || p.nom || '').toString().slice(0, 120);
  var texto = (p.comentario || '').toString().slice(0, MAX_TXT);
  if (!id || texto.length < 3) {
    return _json({ ok: false, error: 'datos incompletos' });
  }
  var nombre = (p.nombre || '').toString().slice(0, 120);
  var email  = (p.email || '').toString().slice(0, MAX_META);
  var tipo   = (p.tipo || '').toString().slice(0, 40);
  var now = new Date();
  _sheet().appendRow([now, id, tipo, nombre, email, texto]);
  if (NOTIFY_EMAIL) {
    try {
      MailApp.sendEmail(NOTIFY_EMAIL, 'Nuevo comentario · ' + id,
        'ID: ' + id + '\nTipo: ' + tipo + '\nNombre: ' + nombre + '\nCorreo: ' + email + '\n\n' + texto);
    } catch (err) {}
  }
  return _json({ ok: true, comment: { n: nombre, t: texto, ts: now.getTime() } });
}
