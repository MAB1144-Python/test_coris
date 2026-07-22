# Agente de clasificación — Coris Latinoamérica

Challenge técnico: AI Automation Engineer. Agente que recibe un mensaje de
texto (simulando una solicitud entrante de un viajero o prestador), lo
clasifica usando **Claude API con Tool Use**, y ejecuta la acción
correspondiente según la categoría detectada.

## Setup

Requisitos: Python 3.10+.

```bash
# 1. Clonar / entrar al repo
cd test_coris

# 2. (Recomendado) crear un entorno virtual
python -m venv .venv
source .venv/bin/activate        
### Windows: 
.venv\Scripts\activate

# 3. Instalar dependencias
pip install -r requirements.txt
```

### Cómo pasar la API key

La API key se lee **únicamente** desde la variable de entorno
`ANTHROPIC_API_KEY` (nunca está hardcodeada en el código). Dos formas de setearla:


```bash
export ANTHROPIC_API_KEY="sk-ant-..."        # macOS/Linux
$env:ANTHROPIC_API_KEY = "sk-ant-..."        # Windows PowerShell
```

## Cómo correrlo

```bash
python agent.py
```

Al iniciar aparece un menú para elegir la versión:

- **Demo** — procesa los 4 mensajes de prueba incluidos en el challenge y muestra
  por consola, para cada uno: el mensaje recibido, cada tool invocada por Claude
  (con su input y resultado), y la respuesta final generada.
- **Interactiva** — funciona como un chat: escribís tus propios mensajes y el
  agente los clasifica y responde en vivo, con la misma traza de tools. Escribí
  `salir` (o una línea vacía) para volver al menú.

En ambos casos, los casos que se registran quedan persistidos en `casos.json`
(se crea en el primer run).

## Estructura del proyecto

```
agent.py        # entry point: loop de orquestación (Tool Use) + output por consola
tools.py        # definición de las 3 tools (JSON Schema) + su implementación real
requirements.txt
.env.example
```

## Cómo funciona el agente

1. `agent.py` manda el mensaje a Claude junto con las 3 tools disponibles y
   un system prompt que le indica el procedimiento a seguir.
2. Claude decide, mensaje por mensaje, qué tool llamar y con qué
   argumentos — no hay un flujo hardcodeado tipo `if/else` en el código que
   decida la categoría; eso lo determina Claude vía Tool Use.
3. El loop en `agent.py` ejecuta la tool solicitada, le devuelve el
   resultado a Claude como `tool_result`, y repite hasta que Claude termina
   el turno (`stop_reason != "tool_use"`), con un tope de `MAX_TURNOS` para
   evitar loops infinitos.

Flujo esperado para cada categoría:

| Categoría | Tools que se invocan |
|---|---|
| `SOLICITUD_NUEVA` | `clasificar_mensaje` → `registrar_caso` → `generar_respuesta` |
| `SEGUIMIENTO` | `clasificar_mensaje` → `generar_respuesta` |
| `PRESTADOR` | `clasificar_mensaje` → `generar_respuesta` |
| `OTRO` | `clasificar_mensaje` → `generar_respuesta` |

## Decisiones de diseño

**¿Por qué estructuré el agente así?**

- **`clasificar_mensaje` no es reglas hardcodeadas — es un llamado propio a
  Claude con salida estructurada.** En vez de clasificar con `if "caso" in
  texto` o listas de palabras clave, la tool hace su propio llamado a la
  Messages API (`output_config.format` con JSON Schema) para clasificar el
  mensaje usando comprensión semántica real. Esto tiene dos ventajas: (1)
  la clasificación entiende paráfrasis y contexto en vez de coincidencias
  literales, y (2) desacopla la lógica de clasificación del agente
  orquestador — el día de mañana se podría reemplazar por un clasificador
  propio (fine-tuned, embeddings, lo que sea) sin tocar el loop principal
  ni el system prompt del orquestador.

- **`generar_respuesta` es por plantillas, no otro llamado a Claude.** Acá
  tomé la decisión inversa a propósito: el mensaje final es texto de cara
  al viajero con requisitos de contenido puntuales del challenge (confirmar
  recepción + "un asesor se contacta en X minutos", etc.). Para ese tipo de
  copy transaccional priorizo consistencia y control determinístico del
  tono por sobre la variabilidad de un LLM — con plantillas garantizo que
  el mensaje cumple los requisitos siempre, sin depender de que Claude no
  se "olvide" de mencionar el número de caso o el tiempo de contacto.

- **`registrar_caso` guarda en un JSON plano (`casos.json`), no en una
  base de datos.** El challenge explícitamente no pide persistencia
  compleja; un archivo JSON es suficiente para simular el alta de un caso
  y es trivial de inspeccionar para el evaluador.

- **Loop manual de Tool Use (no el Tool Runner del SDK).** Preferí escribir
  el loop `while` a mano en vez de usar `client.beta.messages.tool_runner`
  (todavía beta en el SDK de Python) para que el código corra igual en
  cualquier versión reciente del SDK, sin depender de una feature en beta,
  y para que el flujo completo (qué se le manda a Claude, qué se ejecuta,
  qué se le devuelve) quede explícito y fácil de auditar en una sola
  lectura de `agent.py`.

- **Casos borde contemplados:**
  - Si Claude llama una tool que no existe o con argumentos inválidos, el
    error se captura y se le devuelve como `tool_result` con
    `is_error: true`, para que Claude pueda recuperarse en vez de que el
    proceso se caiga.
  - Si el mensaje no encaja en ninguna categoría de negocio (ej. consulta
    comercial), cae en `OTRO` y se genera una respuesta genérica derivando
    al equipo correspondiente, en vez de forzarlo a una de las otras 3
    categorías.
  - `MAX_TURNOS` acota el loop por mensaje para que un comportamiento
    inesperado del modelo (o una tool que se llama en bucle) no cuelgue el
    proceso indefinidamente.
  - El modelo es configurable vía `CLAUDE_MODEL` (default `claude-opus-4-8`)
    para poder bajar a un modelo más económico en producción sin tocar
    código.

## Lo que no incluye (a propósito)

Por alcance del challenge: sin UI, sin base de datos real, sin integración
con WhatsApp/email, sin tests unitarios, sin deploy. El foco está en la
lógica del agente y su Tool Use.
