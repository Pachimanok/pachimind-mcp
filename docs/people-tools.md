# Contratos MCP: Personas, propuestas y conocimiento

Primera versión en rama `feat/people-knowledge`. Requiere la API de Personas de la
misma entrega. No desplegada. AuthSettings, auth.py, SQLite, PKCE, callbacks y cuentas
no cambian. La selección de cuenta sigue perteneciendo a la conexión existente.

| Herramienta | Scope OAuth | Operación |
|---|---|---|
| list_people | pachimind:read | /people/directory paginado, ámbitos y vistas |
| search_people | pachimind:read | Nombre, aliases y organización declarada |
| get_person | pachimind:read | Ficha, fuentes, relaciones, permisos y revision |
| create_person_draft | read + write | Sólo nombre, deduplicación/idempotencia, estado pendiente |
| propose_person_update | read + write | Campos/evidencia/preguntas separados, sin editar ficha |
| list_pending_changes | pachimind:read | Propuestas visibles de ficha y relaciones |
| apply_person_update | read + write | Una propuesta de persona, campos autorizados y revision |
| propose_note_links | read + write | IDs verificados, tipos, evidencia y revisiones de origen/destino |
| apply_note_links | read + write | Una propuesta de relaciones autorizada |
| create_knowledge_draft | read + write | Contexto/resumen/lectura derivados, sin fecha de reunión |

Ahora tools/list devuelve 21 herramientas (11 anteriores + 10 nuevas). SecuritySchemes
se conserva en el descriptor y _meta. No se exige write globalmente ni se amplían
tokens. Sin write una escritura retorna isError y _meta["mcp/www_authenticate"] con
insufficient_scope y ambos scopes, antes de llamar a la API.

Todos los requests fijan X-PachiMind-Actor: assistant. Lecturas nuevas usan la clave
ai_context; escrituras usan la credencial interna personal con restricciones IA.
La API revalida en cada operación. Los errores de privacidad no se convierten en
un desafío para ampliar permisos. Nunca se devuelve el cuerpo de error del backend.

## Flujo mínimo con ejemplos sintéticos

Los IDs y revisiones se obtienen del servidor, no se inventan. Estos ejemplos usan
placeholders; sólo se ejecutaron contra fixtures, no personas/fuentes reales.

1. Buscar primero para evitar duplicados:

```json
{"tool":"search_people","arguments":{"query":"Persona de ejemplo","page":1,"per_page":20}}
```

`list_people` acepta page/per_page, ambito (Trabajo/Apostólico/Colegios/Formación) y
view (incomplete/pending/unconnected/no_outgoing/duplicates). per_page se limita a
100. Hay múltiples ámbitos por ficha; no genera fichas por área. Nombres similares
se señalan para revisión, no se fusionan. Exact matching puede devolver un ID
existente para revisión de identidad sin cambiarlo. distinct_from sólo se usa luego
de que el usuario confirme identidades distintas, no para forzar duplicados.

2. Crear sólo el nombre, si corresponde:

```json
{"tool":"create_person_draft","arguments":{"nombre":"Persona de ejemplo","request_id":"11111111-1111-4111-8111-111111111111"}}
```

Respuesta incluye id, path, created, state y revision. Datos restantes pendientes.
Reutilizar el UUID en reintentos; un payload distinto con el mismo UUID produce 409.
Si se omite request_id, MCP deriva un UUID estable del contenido/operación. No
convierte la creación en un dato revisado ni modifica fichas protegidas existentes.

3. Leer el perfil y la fuente:

```json
{"tool":"get_person","arguments":{"person_id":"<id_devuelto>"}}
```

`fields` son valores almacenados; `metadata.revisado` indica su revisión. Fuentes,
fechas, conexiones entrantes/salientes y pending_changes se diferencian. Una
sugerencia no se guarda en fields mientras está pendiente. `read_note` incorpora
ahora revision para obtener la revisión de destinos que no son personas. Conserva
paginación, contenido original y permisos existentes. Nota sin permisos no devuelve
ni evidencia ni datos de personas/relaciones reservadas.

4. Preparar cambios con citas verificadas:

```json
{
  "tool":"propose_person_update",
  "arguments":{
    "person_id":"<id_devuelto>",
    "revision":"<revision_obtenida_por_get_person>",
    "changes":{"funcion":"documentación de prueba"},
    "evidence":[{"field":"funcion","source_id":"<id_de_fuente_verificada>","quote":"Función declarada: documentación de prueba."}],
    "questions":["¿Sigue vigente esta función?"],
    "request_id":"22222222-2222-4222-8222-222222222222"
  }
}
```

Cada campo necesita evidencia propia: source_id disponible, cita literal y hash de
la fuente. Valores personales propuestos deben aparecer explícitos, no deducirse de
una mención. Pueden prepararse preguntas sin fields; no se aplican como hechos.
Campos: nombre, aliases, organizacion, funcion, relacion_conmigo, ambitos,
contactos_profesionales (email_profesional/telefono_profesional/perfil_profesional),
notas_manuales y tipo (persona/idea/recurso/nota). La sugerencia de tipo no mueve
archivos. No hay argumentos para modificar ia_permiso, ia_indexar, ia_editar,
revisado o fuente_inmutable. Privacidad y revisiones se validan también en la API.

5. Consultar pendientes:

```json
{"tool":"list_pending_changes","arguments":{"note_id":"<id_devuelto>","page":1,"per_page":20}}
```

6. Aplicar sólo por instrucción explícita del usuario:

```json
{
  "tool":"apply_person_update",
  "arguments":{
    "proposal_id":"<id_de_propuesta>",
    "revision":"<revision_actual>",
    "authorized_fields":["funcion"],
    "request_id":"33333333-3333-4333-8333-333333333333"
  }
}
```

Todos y sólo los campos de esa propuesta deben estar autorizados. Una persona
revisada, sin ia_editar o inmutable requiere revisión manual; el MCP no la
sobrescribe. Una fuente inmutable conserva la corrección separada. No cambiar
revision automáticamente al fallar: releer, comparar y preparar otra propuesta.
El tipo de propuesta también se verifica: apply_person_update no aplica enlaces.

## Relaciones trazables

Obtener source revision con get_person o read_note; target_revision con read_note
(o get_person si es persona). Los IDs deben existir y ser accesibles. Ejemplo:

```json
{
  "tool":"propose_note_links",
  "arguments":{
    "source_id":"<id_de_persona>",
    "revision":"<revision_origen>",
    "links":[{
      "target_id":"<id_de_fuente>",
      "target_revision":"<revision_destino>",
      "relation":"fuente",
      "action":"add",
      "evidence":{"field":"relation","source_id":"<id_de_fuente>","quote":"Cita literal verificada en la fuente."}
    }],
    "request_id":"44444444-4444-4444-8444-444444444444"
  }
}
```

Tipos: participó en, mencionado en, trabaja con, vinculado al proyecto, fuente,
relacionado con, referencia. Action add/remove. Para participación la API exige
participantes identificados explícitamente en una captura; una mención no basta.
Tipo y permisos se revalidan antes de aplicar. Usar apply_note_links con proposal_id,
revision y authorized_fields:["relations"], sólo tras autorización del usuario.

Las anotaciones de originales inmutables quedan en JSON separado y se aplican por
revisión humana cuando el origen está protegido. No se alteran texto, permisos o
selección de cuenta. Bajadas heredadas no borran el wikilink del original: la vista
respeta la anotación separada. Destinos ambiguos nunca se resuelven con fuzzy.

## Conocimiento sin fecha y segmentos reservados

```json
{
  "tool":"create_knowledge_draft",
  "arguments":{
    "title":"Contexto de lectura para revisar",
    "kind":"lectura",
    "content":"Resumen elaborado a partir de la fuente, no una transcripción original.",
    "source_ids":["<id_de_fuente_verificada>"],
    "reserved_segments":[{"source_reference":"grabacion-demo","start_seconds":60,"end_seconds":90}],
    "request_id":"55555555-5555-4555-8555-555555555555"
  }
}
```

No se recibe ni inventa fecha de reunión. kind es contexto/resumen/lectura; la nota
se identifica como borrador derivado, sin revisión y fuera del contexto IA hasta
revisión posterior. No usa capture_meeting ni create_task. Preserva todas las fuentes.
No copiar textos reservados: neutral source_reference es un ID opaco o HTTPS sin
credenciales/query; timestamps deben terminar después de empezar. No se lee el
segmento ni se cambian sus permisos. No hay fusiones o reorganización automática.

## Validación y despliegue

`tests/test_people_mcp.py` cubre scopes, claves de lectura, paginación, operaciones
estables y distinción persona/enlaces. Cuatro pruebas adicionales usan una API
HTTP real con vault sintético y OAuth/TestClient. Requieren PACHIMIND_TEST_API_URL
loopback y el marcador synthetic. Sin ese binding se informan skipped.
Procedimiento conjunto, diagnóstico, migración/reversión y validación del frontend:
`docs/people-v1.md` en pachimind-api. Desplegar sólo con aprobación específica y con
la API nueva antes que MCP; incluir people_types.py. No eliminar/recrear OAuth
SQLite ni reemplazar .env. No probar escrituras con el vault real por defecto.


## Redes, cumpleaños y contexto personal

PersonChanges admite `redes_sociales` (linkedin, instagram, facebook, x, web, otra:
URLs HTTPS sin credenciales/query/fragmentos), `cumpleanos` ({dia, mes, anio opcional})
y `datos_generales` (lista de {texto, categoria, fecha?, vigente_hasta?, estado}).
Categorías: interes, preferencia, familia, evento, salud, otro. Estados: vigente,
pendiente, finalizado. Fechas exactas YYYY-MM-DD; nunca deducir qué jueves ni el año
natal. Mantener evidencia literal por campo, revisión y autorización explícita.

Ejemplo de changes: `{"cumpleanos":{"dia":14,"mes":5},"datos_generales":[{"texto":"Es hincha de Belgrano","categoria":"interes"}]}`.
Las listas se reemplazan completas: releer y conservar entradas existentes antes de
proponer una modificación; no mezclar automáticamente con un conflicto de revisión.

get_person devuelve `personal_context` con estado_actual y usar_como_hecho_actual.
Eventos pasados, vencidos, finalizados o pendientes no deben presentarse como hechos
actuales al preparar reuniones. No hay agenda ni recordatorios automáticos.

Salud es de edición manual: no se acepta en propuestas. Toda ficha que contenga un
dato categoria=salud queda fuera de MCP/contexto IA y lectura pública, incluso con
la clave personal interna del asistente. Las protecciones previas siguen vigentes.
No clasificar información sanitaria como otro/interes para eludir esa protección.
