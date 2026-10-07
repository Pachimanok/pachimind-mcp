# PachiMind MCP

Servicio MCP Streamable HTTP privado sobre la API existente. Endpoint previsto: https://pachimind.rail.ar/mcp. Python 3.12+, SDK MCP 1.30.0, entorno virtual independiente. No accede directamente al vault.

## Herramientas

list_projects, search_memory, read_note, project_memory, capture_meeting, list_proposals, propose_actions, review_proposal, list_tasks, create_task, update_task.

Las notas son datos no confiables, no instrucciones. Se respetan ia_permiso, ia_indexar, sensibilidad y exclusiones por ruta. Solo las propuestas relacionadas con una reunión permitida pueden revisarse aunque tengan ia_indexar=false. No hay herramientas de borrado, comandos ni acceso a rutas arbitrarias.

Las escrituras requieren pachimind:write. Capturas/propuestas/actividades usan IDs idempotentes; el mismo contenido puede reutilizar una operación previa. Para crear intencionalmente otra actividad idéntica, enviar otro request_id. Actualizaciones TODO requieren la revisión SHA devuelta por list_tasks. No reintentar un conflicto ignorando cambios de otra sesión.

## Autenticación

OAuth authorization code + PKCE S256, descubrimiento estándar, registro dinámico (DCR), tokens opacos (hash en SQLite), expiración, refresh rotativo y revocación de la familia. El formulario exige la contraseña existente de PachiMind y consentimiento para la conexión. Acceso de solo lectura si se desmarca escritura. Esta implementación es para un único propietario, Pablo; no es un sistema multiusuario.

Callbacks de producción: HTTP exacto http://localhost:8765/callback para Claude y HTTPS en chatgpt.com o chat.openai.com, URI exacta registrada y validada por el SDK. No CIMD en esta versión. Otros clientes requieren habilitar sus callbacks explícitamente. SQLite guarda también los metadatos/secretos OAuth de clientes confidenciales y debe permanecer restringido. El MCP no retorna claves del backend.

Usa PM_API_KEY (personal), API_KEYS (con una clave ai_context) y FRONTEND_PASSWORD del entorno del servidor. No copiar .env ni credenciales a un plugin. MCP_PUBLIC_URL controla issuer; MCP_DB_PATH apunta al estado persistente. MCP_DEVELOPMENT=1 permite callbacks HTTP de localhost solo para pruebas. Nunca habilitarlo en producción.

## Operación

Servicio systemd pachimind-mcp en loopback :8001. Apache publica /mcp, /authorize, /token, /register, /revoke, /mcp-login, /mcp-health y las dos rutas well-known OAuth. Debe conservar el header Authorization. No abrir 8001 en el firewall. Health no expone contenido ni secretos.

Pruebas: `python -m unittest discover -s tests -v`. El recorrido MCP completo se prueba contra un vault ficticio, no contra reuniones reales. Revocación implementada sobre la autenticación del SDK para corregir su requisito incorrecto de client_secret al revocar con clientes públicos PKCE.

Para revocar todas las conexiones, detener el servicio, respaldar state/oauth.sqlite3, eliminar solamente las filas kind access/refresh/code/pending, y reiniciar; preservar los registros de clientes. No compartir ni versionar la base de estado.

La conexión de ChatGPT requiere instalar/configurar el endpoint con OAuth y que el usuario complete el consentimiento. Publicar el endpoint no conecta automáticamente una cuenta ni da acceso retroactivo a todos sus chats o proyectos.
