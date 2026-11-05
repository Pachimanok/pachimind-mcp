# Claude: conector remoto OAuth

Configuración de la interfaz del cliente:

- URL: https://pachimind.rail.ar/mcp
- OAuth: Registrar automáticamente (DCR).
- No elegir identidad publicada/CIMD: el servidor no la implementa.
- No ingresar ID/secret propios ni encabezados con credenciales internas.
- Completar el formulario OAuth de PachiMind y elegir lectura o autorizar escritura.

Se reprodujo en producción el rechazo de DCR para el callback HTTPS de Claude:
HTTP 400, invalid_redirect_uri. Se agrega sólo la URI exacta
https://claude.ai/api/mcp/auth_callback. No se autorizan otros paths, query strings,
fragmentos, credenciales en URL, puertos alternativos o subdominios. Se mantiene la
política existente de ChatGPT y del callback local exacto; no habilitar desarrollo
en producción para solucionar una conexión.

Esto no amplía scopes globales, no autoriza escritura sin consentimiento y no
modifica permisos del vault ni las conexiones existentes. Mantiene PKCE S256,
validación de resource, CSRF, expiraciones, refresh y revocación. No se implementa
CIMD ni un cliente OAuth global con secretos compartidos.

Pruebas: registro y flujo completo PKCE con callback de Claude, read sin posibilidad
de guardar y read+write sólo después de consentimiento explícito. Se rechazan diez
variantes del callback y siguen las regresiones existentes (40 pruebas totales,
seis integraciones omitidas si no se inicia la API sintética).

Despliegue: sólo auth.py, sobre su SHA previo conocido, con respaldo privado,
pruebas del paquete exacto y reinicio MCP. Conservar SQLite y clientes ajenos.
Verificar DCR del callback y flujo PKCE real con un cliente temporal read; revocar
y limpiar sólo ese cliente. Ninguna nota ni tarea real es necesaria para el diagnóstico.
Rollback: restaurar auth.py anterior del respaldo y reiniciar MCP. No borrar OAuth
ni notas. Nuevos clientes de Claude podrían no reautorizar hasta volver a habilitar
el callback; no revocar indiscriminadamente conexiones existentes.

La prueba automatizada valida el servidor y callback. El usuario debe confirmar la
conexión desde Claude: completar OAuth y luego pedir leer la nota de reglas vigentes
con read_note, limit=20000. No afirmar conexión real de Claude antes de esa prueba.
