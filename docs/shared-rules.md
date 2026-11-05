# Preferencias compartidas con punto de entrada estable

No se agrega una herramienta ni se cambia el contrato de read_note. Cada agente
recibe un bootstrap que pide leer la nota:

- ID: 07-conocimiento-contexto-pachimind-reglas-vigentes
- Ruta: 07 Conocimiento/Contexto/pachimind-reglas-vigentes.md
- Leer con limit=20000 y completar next_offset si existe.

Las preferencias aprobadas por el propietario quedan subordinadas a instrucciones
superiores y permisos reales. Otra nota no puede autodeclararse fuente de reglas.
El bootstrap no habilita nuevas escrituras ni cambia el scope de lectura. Si la
nota no está disponible, el agente debe explicar esa limitación, no inventar reglas.

La nota aprobada es activa, revisada, legible por IA, inmutable para la API y no
editable por IA. Sensibilidad interno impide su exposición al scope público. Esta
activación específica no cambia ningún otro borrador ni nota. El cuerpo tiene su
versión y aprobación visibles; un registro privado .pachimind/rules/active.json
conserva ID, versión, hash y procedencia de aprobación. Es una constancia de
activación, no un endpoint nuevo ni una garantía ante ediciones directas del
propietario en el sistema de archivos.

Nuevas versiones requieren autorización explícita y una operación administrativa
que conserve respaldo e historia; create_note sólo crea propuestas/borradores y
no puede activar reglas. No se creó una herramienta MCP para modificar la fuente.
Las restricciones de fuente inmutable bloquean PATCH y DELETE de esa nota por API.

## Validación y despliegue

Las pruebas MCP verifican bootstrap en initialize para un cliente read, lectura
completa sin herramienta adicional y rechazo si la nota deja de ser legible por IA.
Se probaron por separado, con vault sintético, lectura permitida, bloqueo público,
rechazo de cambios/borrado e integridad del original; y escritura create-only del
instalador, que rechaza colisiones sin sobrescribir datos.

La activación administrativa se realiza con contenido aprobado aparte del repo:
no se versiona aquí el cuerpo privado de las preferencias. Crea una única nota y
un registro privado, guarda respaldo del server.py anterior y actualiza sólo las
instrucciones del MCP, conservando herramientas y OAuth. El instalador valida
hashes, prueba el código exacto y revierte sólo lo que creó si falla. No sobreescribe
una nota o registro de reglas preexistente diferente.

Después se debe verificar por el MCP público con OAuth read: initialize contiene
el ID de entrada y read_note devuelve el cuerpo completo con el hash aprobado.
Revocar/eliminar sólo el cliente temporal de diagnóstico; no borrar otras conexiones.

Rollback administrativo: restaurar server.py anterior y reiniciar MCP; para retirar
la activación, comprobar antes los hashes registrados en activation.json y retirar
únicamente la nota y registro creados. No tocar otras notas o OAuth, ni borrar reglas
que alguien haya modificado posteriormente. Esto desactiva la versión, no debe
presentarse como una nueva versión aprobada. No ejecutar sin fallo o pedido.

## Instalación en agentes

MCP initialize incluye el bootstrap para nuevos clientes. No se presupone que un
chat existente vuelva a leerlo. Para DOT u otro agente existente, el propietario
pega una instrucción de entrada con ese ID y pide confirmar versión y criterios sin
escribir nada. El acceso a la nota no demuestra por sí solo que el agente ya la leyó
ni que la recuerde en sesiones nuevas; verificar la primera lectura y conservar el
bootstrap en el mecanismo de instrucciones persistentes que ese agente admita.
