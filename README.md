# Agente de clasificación — Coris Latinoamérica

Agente que clasifica mensajes de viajeros y prestadores usando Claude API con Tool Use.
Categoriza automáticamente, registra casos nuevos y genera respuestas personalizadas.

**Autor:** Msg. Brayan Andru Montenegro Embus  
**Repositorio:** https://github.com/MAB1144-Python/test_coris  
**Redes:** [GitHub](https://github.com/MAB1144-Python) · [LinkedIn](https://www.linkedin.com/in/brayanandrumontenegroembus)

---

## Descarga del repositorio

```bash
git clone https://github.com/MAB1144-Python/test_coris.git
cd test_coris
```

## Instalación

**Requisitos:** Python 3.10+

```bash
python -m venv .venv
source .venv/bin/activate           # en Linux/macOS

.venv\Scripts\activate              # en Windows:

pip install -r requirements.txt
```

## API Key

Define la variables de entorno antes de ejecutar y guárdalas en el archivo .env en la misma carpeta del proyecto, debe contener:

ANTHROPIC_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-opus-4-8
CASOS_FILE=casos.json

## Ejecución

```bash
python agent.py
```

Al iniciar te presentamos un menú:

```
AGENTE DE CLASIFICACIÓN - Coris Latinoamérica
Seleccioná una versión:
  1) Demo         - procesa los 4 mensajes de prueba del challenge
  2) Interactiva  - escribí tus propios mensajes y se clasifican
  3) Salir

Opción [1/2/3] >
```

### Versión Demo
Procesa automáticamente 4 mensajes de prueba. Muestra para cada uno:
- Mensaje recibido
- Cada tool invocada (input → resultado)
- Respuesta final generada

### Versión Interactiva
Chat en vivo: escribís mensajes, el agente los clasifica y responde al instante.
Escribe `salir` o una línea vacía para volver al menú.

**Resultado:** Los casos registrados se guardan automáticamente en `casos.json`.

## Arquitectura

**Capas separadas por responsabilidad (SoC):**

- **`agent.py`** — Orquestación: loop manual de Tool Use, manejo de conversación, UI (menú, I/O)
- **`tools.py`** — Capa de negocio: 3 tools con schemas JSON, sus implementaciones, persistencia
- **`casos.json`** — Estado: almacén simple (sin DB, sin transacciones — suficiente para el scope)

**Flujo por categoría:**

| Categoría | Orquestación |
|---|---|
| SOLICITUD_NUEVA | `clasificar_mensaje` → `registrar_caso` → `generar_respuesta` |
| SEGUIMIENTO, PRESTADOR, OTRO | `clasificar_mensaje` → `generar_respuesta` |

El agente orquestador **no decide la categoría ni inventa datos** — es Claude quien, vía Tool Use, elige
la secuencia correcta según el system prompt.

## Decisiones de diseño

**1. Clasificación real, NO hardcodeada**

La tool `clasificar_mensaje` hace un **llamado auténtico a Claude** con `output_config.format: {"type": "json_schema"}`
para clasificación **semántica real**. No hay reglas hardcodeadas tipo `if "caso" in texto` o listas de palabras clave.

Esto significa:
- ✅ Entiende paráfrasis: "Abrí un caso COR-2026-0892" = SEGUIMIENTO
- ✅ Entiende contexto: "Quería saber los países" (sin "caso", sin "médico") = OTRO
- ✅ Claude decide la categoría, no un script de `if/else`

*Trade-off:* Costo de +1 llamado/mensaje vs. **precisión real y extensibilidad**. Permite reemplazar
el clasificador mañana sin tocar la orquestación.

**2. Respuestas = Plantillas, no generación**

`generar_respuesta` usa templates por categoría. No llama a Claude.

*Justificación:* Las respuestas son texto transaccional (confirmar recepción, "se contactarán en 15 min").
Las plantillas garantizan cumplimiento de requisitos, tono consistente, y sin sorpresas del modelo.
Trade-off: menos variabilidad de texto vs. control determinístico.

**3. Loop manual, no Tool Runner beta**

Implementé el `while stop_reason == "tool_use"` a mano en lugar de `client.beta.messages.tool_runner`.

*Razón:* Explicititud (todo el flujo es visible en ~50 líneas), sin dependencias beta, compatible
con cualquier versión reciente del SDK. Mantiene per-turn hooks para error handling: si una tool falla,
se reporta con `is_error: true` y Claude puede recuperarse.

**4. Persistencia = JSON plano**

Sin DB, sin transacciones, sin locking. Un archivo de casos en JSON.

*Por qué:* Alcance del challenge. Es suficiente para simular registro y es trivial de inspeccionar.
Si escala a producción, swappear por SQLite o Postgres sin tocar las interfaces.

**5. Seguridad = Entorno, nunca hardcodeado**

API key desde `ANTHROPIC_API_KEY` (validada en `main()`). Nunca en el código. `.gitignore` protege
`.env` y `casos.json`.

*Patrón:* 12-factor app. Configurable por entorno sin recompilación.

**6. Extensibilidad = Dispatcher limpio**

Nueva tool → agregar a `TOOLS` en `tools.py`, implementar función, extender `ejecutar_tool()`.
Orquestador (`agent.py`) no cambia.

*Patrón aplicado:* Open/Closed principle (SOLID). Abierto a extensión (nuevas tools), cerrado a
modificación (orquestador estable).
