# Ampliación OAuth de lectura a escritura

Cambio preparado para revisión. No se ejecutó ningún despliegue ni se modificó
la configuración de producción. Tampoco se guardó la reunión pendiente.

## Comportamiento

- La metadata RFC 9728 de `/mcp` anuncia `pachimind:read` y `pachimind:write`.
  El middleware sigue exigiendo solamente lectura globalmente. Su desafío HTTP
  inicial incluye `scope="pachimind:read"` para orientar la autorización mínima.
- FastMCP 1.30.0 publica `meta=` sólo como `_meta` en `tools/list`. Se conserva
  la declaración existente de scopes y se refleja en `securitySchemes` de nivel
  superior, como en el ejemplo oficial de OpenAI, sin mantener otra política.
- Una herramienta de escritura con token de lectura retorna un resultado MCP
  de error con `_meta["mcp/www_authenticate"]`. No llama al backend, ni siquiera
  para leer el proyecto. Los errores de privacidad siguen siendo errores de
  herramienta normales y no piden una ampliación de permisos.
- La nueva autorización usa código + PKCE y ambos scopes. La casilla de escritura
  aparece desmarcada. Aceptarla permite escritura; dejarla desmarcada conserva
  lectura. Enviar `write=yes` sin haber solicitado escritura no la concede.
- Omitir `scope` solicita lectura. Los scopes admitidos en el registro de un
  cliente describen capacidades, no permisos concedidos. No se amplían tokens
  existentes ni se puede ampliar un permiso mediante refresh.
- Se mantienen validación de recurso, expiración, revocación, restricciones de
  las notas e idempotencia. No hay migración de SQLite ni cambio de dependencias.

Ejemplo del desafío, usando el issuer público configurado:

```json
{
  "isError": true,
  "content": [{"type": "text", "text": "Permiso insuficiente: volvé a conectar PachiMind y autorizá pachimind:read pachimind:write"}],
  "_meta": {
    "mcp/www_authenticate": [
      "Bearer error=\"insufficient_scope\", scope=\"pachimind:read pachimind:write\", resource_metadata=\"https://pachimind.rail.ar/.well-known/oauth-protected-resource/mcp\""
    ]
  }
}
```

El resultado de herramienta viaja dentro de una respuesta JSON-RPC HTTP 200,
siguiendo el mecanismo de autenticación de Apps SDK. Los rechazos de transporte
por token ausente/inválido o falta de lectura siguen siendo HTTP 401/403 con
`WWW-Authenticate`; no se convierten en errores genéricos de herramienta.

## Fundamento y validación

Se consultó la [especificación MCP 2025-11-25](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/basic/authorization.mdx),
en particular discovery, scope selection y scope challenge handling. El desafío
incluye los scopes anteriores necesarios además del nuevo, para no perder lectura.

Para ChatGPT se inspeccionaron el [ejemplo oficial de autenticación de OpenAI](https://github.com/openai/openai-apps-sdk-examples/blob/18cc38e78a968712c357bacdc3c79fead5bfc6b4/authenticated_server_python/main.py)
y su [README](https://github.com/openai/openai-apps-sdk-examples/blob/18cc38e78a968712c357bacdc3c79fead5bfc6b4/authenticated_server_python/README.md),
que enlaza la [guía de autenticación](https://developers.openai.com/apps-sdk/build/auth/#triggering-authentication-ui).
El acceso directo a los sitios de documentación fue bloqueado por la red de este
entorno; las fuentes oficiales de GitHub sí fueron accesibles. Se inspeccionó
también el código de la versión instalada de FastMCP, 1.30.0.

Desde `/workspace/pachimind-mcp`:

```bash
PYTHONDONTWRITEBYTECODE=1 /workspace/.venvs/pachimind-mcp/bin/python -m unittest discover -s tests -v
```

Resultado: 19 pruebas aprobadas, incluidas las 9 preexistentes. Cubren lectura
real del resultado de una nota ficticia; las cinco herramientas de escritura
sin llamadas al backend cuando falta permiso; parsing del desafío Bearer;
discovery y ambas ubicaciones de `securitySchemes`; aceptación/rechazo usando un
callback HTTPS permitido de ChatGPT; ausencia de ampliación de tokens anteriores,
scope omitido y refresh; notas excluidas; y tokens inválidos, vencidos, revocados,
de otro recurso o sin lectura. Toda la integración usa fixtures, SQLite temporal
y backend simulado. No es una validación de la interfaz real de ChatGPT.

También pasó una comprobación contra un proceso Uvicorn real en loopback: salud,
discovery, registro dinámico, PKCE, consentimiento de sólo lectura, desafío de
`capture_meeting` y los 11 descriptores de herramientas. Usó credenciales ficticias,
SQLite temporal y una URL de backend sin servicio; no contactó el backend real.

## Despliegue después de la revisión

1. Revisar el commit y conservar la revisión actualmente desplegada para rollback.
   Si producción usa Git, registrar `git rev-parse HEAD` y comprobar que el árbol
   está limpio; no sobrescribir cambios locales. La base de este cambio es
   `1c0a84e9d43bb9c81c6d2a9cd3f6482268cc8a6f`.
2. Probar el commit aprobado en staging con Python 3.12+ y `requirements.txt`.
   Ejecutar la suite anterior usando el Python del virtualenv de staging. Las
   pruebas establecen sus propias variables ficticias; no necesitan secretos reales.
   Confirmar que MCP sigue en 1.30.0. No actualizar dependencias como parte del despliegue.
3. En una ventana autorizada, detener `pachimind-mcp`, aplicar únicamente el commit
   aprobado por el mecanismo habitual de despliegue y reiniciar el servicio.
   En el checkout Git limpio que describe el servicio, sería:

   ```bash
   cd /srv/pachimind/mcp
   sudo systemctl stop pachimind-mcp
   git cherry-pick COMMIT_APROBADO
   sudo systemctl start pachimind-mcp
   sudo systemctl is-active pachimind-mcp
   ```

   Si el servicio se instala desde un artefacto, usar el artefacto de esa revisión,
   no ejecutar los comandos Git anteriores. Conservar `.env`, issuer, endpoints,
   Apache, permisos y `state/oauth.sqlite3`. No activar `MCP_DEVELOPMENT` ni borrar
   filas, clientes o tokens. El cambio no requiere editar configuración de producción.
4. Verificar `/mcp-health`, la metadata pública del recurso con ambos scopes y el
   desafío inicial de lectura de `/mcp`. Verificar que Apache conserve Authorization
   y WWW-Authenticate y que no sirva metadata antigua. No imprimir cabeceras de
   autorización, tokens, secretos ni contenido privado en los registros de diagnóstico.
5. En ChatGPT, refrescar las herramientas/reconectar PachiMind si conserva discovery
   anterior. Si un cliente antiguo fue registrado únicamente con lectura, el SDK
   rechazará solicitar escritura con `invalid_scope`: será necesario registrarlo
   nuevamente al reconectar. No editar sus scopes ni sus tokens en SQLite.
6. Comprobar lectura y la ampliación de permisos con un proyecto/reunión ficticios
   permitidos: rechazar escritura debe conservar lectura y no crear la reunión;
   aceptarla debe permitir la captura. Revisar el resultado real de reconexión con
   el usuario antes de guardar la reunión pendiente. Conservar el mismo request_id
   en reintentos de esa captura para evitar duplicados.

## Rollback

1. Detener `pachimind-mcp` y restaurar el artefacto de la revisión anterior registrada.
   En un despliegue por Git, revertir sólo `COMMIT_APROBADO` mediante
   `git revert --no-edit COMMIT_APROBADO`; no usar reset destructivo ni borrar estado.
2. Reiniciar el servicio y verificar salud y lectura. La revisión anterior vuelve
   a anunciar sólo lectura y a devolver el error de escritura anterior sin desafío.
3. Conservar SQLite y credenciales: no hay migración que revertir. El rollback de
   código no revoca permisos ya consentidos. Si se decide retirar una conexión
   nueva, revocarla por el flujo OAuth existente, sin eliminar otras conexiones.
   ChatGPT puede necesitar reconexión para refrescar metadata después del rollback.
