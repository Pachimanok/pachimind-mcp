# Guardar notas libres con create_note

Ampliación sobre la rama Personas `fbc9383`. La rama main antigua todavía contiene
sólo las once herramientas anteriores; no usarla para reemplazar una instalación
con Personas. Esta rama conserva las 21 y agrega create_note (22 en total).

## Contrato

`create_note(title, content, kind="contexto", source_ids=[], reserved_segments=[], request_id=None)`.
Título de 1 a 200 caracteres y contenido Markdown no vacío de hasta 50000.
kind: contexto (por defecto), resumen o lectura. source_ids son IDs reales del vault,
no URLs o rutas arbitrarias. Para fuentes externas se puede indicar procedencia en
el contenido, distinguiendo lo recibido de lo elaborado, sin secretos ni citas reservadas.
No hay argumento path, fecha de reunión, participantes, aprobación o publicación.

Requiere OAuth read + write; la lectura global sigue requiriendo sólo read. No exige
una nueva cuenta ni cambia SQLite, clientes, callbacks o permisos de notas existentes.
La pantalla de consentimiento describe ahora las notas además de reuniones/TODO.
El MCP usa X-PachiMind-Actor: assistant en el backend y conserva el filtro por fuente.

Implementación: la operación existente POST /notes/knowledge-drafts. No cambia API,
web, dependencias ni formato del vault. Contexto/resumen se guardan bajo
07 Conocimiento/Contexto; lectura bajo 07 Conocimiento/Recursos. Las notas conservan
estado borrador, revisado=false, ia_indexar=false e ia_editar=false. No inventar una
fecha. Un texto que enumera acciones no crea ni aprueba tareas o decisiones.

Respuesta: id, path, created y state=pending. La herramienta sólo confirma guardado
con recibo completo. Un error no confirma éxito ni ausencia de escritura: conservar
request_id y verificar antes de reintentar. Si no se proporciona UUID, el MCP deriva
uno del contenido; idéntico payload produce la misma operación. Los dos nombres
create_note/create_knowledge_draft comparten UUID y payload del backend para evitar
copias al cambiar de nombre en un reintento. Para otra nota intencionalmente idéntica,
usar un nuevo UUID. Si cambia contenido con el mismo UUID, conflicto, no sobrescritura.

Ejemplo sintético:

```json
{
  "title": "Idea recibida en DOT",
  "content": "## Texto recibido\nIdea ficticia para una prueba.\n\n## Nota procesada\nVersión organizada, sin decisiones aprobadas.\n\n## Pendientes\nValidar el planteo.",
  "kind": "contexto",
  "source_ids": [],
  "request_id": "b640ca1f-d1f9-43ab-afb3-9fde0825f3f8"
}
```

La nota existe en disco, pero read_note no debe saltarse ia_indexar=false para
releer un borrador protegido. El recibo de creación confirma el resultado; la
verificación de lectura completa se hace desde la sesión humana con permisos.
El contenido no se envía a Gemini al guardar. Se rechazan fuentes reservadas y
patrones de credenciales. Esto no es un detector universal de datos sensibles:
el agente debe excluirlos antes de enviar la nota.

## Instrucción para DOT u otro chat

> Cuando te pida guardar una nota, organizá su contenido sin inventar hechos.
> Si te pido conservar el original, separá «Texto recibido» de «Nota procesada».
> Usá create_note con el Markdown final, nunca capture_meeting ni create_task para
> simular una nota. Usá IDs de fuentes verificados cuando existan y un request_id
> estable por operación. Guardá sólo después de mi indicación; no apruebes acciones.
> Confirmá el identificador, ruta y estado pendiente devueltos por la herramienta.
> Si falta permiso o la herramienta no está disponible, informalo sin afirmar guardado.

No incluir una orden de guardado automático en cada mensaje: cada chat debe tener
el conector habilitado y el usuario haber pedido el guardado. El MCP no recibe
mensajes por sí solo ni se instala dentro de DOT. Si el chat ve sólo once herramientas,
revisar servidor y actualizar la lista de herramientas de la conexión.

## Validación local

API y MCP deben usar virtualenvs distintos por las versiones de Pydantic.
Iniciar la API sintética de Personas en loopback, puerto 18002; siempre genera vault
temporal y no acepta uno real. Ejecutar desde este repo:

```bash
PACHIMIND_TEST_API_URL=http://127.0.0.1:18002 NO_PROXY=127.0.0.1,localhost PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -v
```

35 pruebas aprobadas, incluidas seis integraciones reales contra API sintética;
sin esa variable las seis se omiten. Cubren descubrimiento/scope, rechazo antes de
I/O sin write, cuerpo preservado, notas sin fecha, borrador pendiente, idempotencia
entre alias, UUID reutilizado con otro contenido, fuentes reservadas, credenciales
ficticias, recibo incompleto y regresiones OAuth/Personas/TODO. No se probó escritura
sobre producción ni se guardó la reunión pendiente.

## Despliegue y reversión

Actualizar sólo server.py de MCP sobre la entrega de Personas conocida, preservando
auth.py, people_types.py, .env y state/oauth.sqlite3. La API existente debe exponer
POST /notes/knowledge-drafts. El instalador verifica ambas condiciones, descarga
un commit fijo, verifica hashes y ejecuta las pruebas con credenciales ficticias y
sin conexión al backend productivo (seis integraciones omitidas). Sólo --apply
instala server.py, respalda su versión previa y reinicia pachimind-mcp. Verifica
salud y la capacidad create_note; ante fallo restaura el archivo previo. No cambia
API/web, OAuth, cuentas, configuración Apache ni datos del vault.

Después, actualizar/reconectar PachiMind en el cliente para renovar tools/list y
comprobar create_note. Reautorizar write sólo si la conexión no lo tiene; una sesión
read sigue leyendo. Abrir un chat nuevo si conserva una lista vieja. No borrar
SQLite ni registrar otra cuenta para resolver una caché de herramientas.

Prueba funcional autorizada: enviar una nota sintética y confirmar id/path/state;
verla con la sesión humana, pendiente y sin fecha de reunión. El chequeo de salud
no crea una nota real. El rollback restaura sólo código usando el archivo privado
server.py.anterior guardado en el directorio BACKUP y reinicia pachimind-mcp;
conserva las notas ya guardadas y todo el estado OAuth.
