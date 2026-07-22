"""
Tools del agente de clasificación de Coris Latinoamérica.

Cada función de este módulo es la implementación real de una tool que Claude
puede invocar mediante Tool Use. `TOOLS` es la lista de definiciones (JSON
Schema) que se pasa a la API; `ejecutar_tool` es el dispatcher que el loop
de agente.py usa para correr la función correspondiente.
"""

import datetime
import json
import os
import random

import anthropic

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")
CASOS_FILE = os.environ.get("CASOS_FILE", "casos.json")

_client = None


def _get_client() -> anthropic.Anthropic:
    """Reutiliza un único cliente para todas las llamadas anidadas a la API."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


# ---------------------------------------------------------------------------
# Definiciones de tools (JSON Schema para la Messages API)
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "clasificar_mensaje",
        "description": (
            "Clasifica semánticamente un mensaje entrante de un viajero o "
            "prestador en una de estas categorías: SOLICITUD_NUEVA, "
            "SEGUIMIENTO, PRESTADOR u OTRO. Devuelve la categoría, un nivel "
            "de confianza (0-1) y un resumen de una línea. Usá esta tool "
            "siempre como primer paso al recibir un mensaje nuevo, antes de "
            "cualquier otra acción."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "texto": {
                    "type": "string",
                    "description": "Texto completo y literal del mensaje recibido.",
                }
            },
            "required": ["texto"],
        },
    },
    {
        "name": "registrar_caso",
        "description": (
            "Registra un caso nuevo de asistencia médica y genera un ID de "
            "caso simulado (formato COR-AAAA-XXXX). Usar únicamente cuando "
            "clasificar_mensaje devolvió la categoría SOLICITUD_NUEVA. No "
            "inventes datos que no estén presentes en el mensaje: si un "
            "campo no se menciona, omitilo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "nombre_viajero": {
                    "type": "string",
                    "description": "Nombre del viajero, si se menciona en el mensaje.",
                },
                "ubicacion": {
                    "type": "string",
                    "description": "País o ciudad donde ocurre la emergencia, si se menciona.",
                },
                "descripcion": {
                    "type": "string",
                    "description": "Descripción breve de la emergencia o necesidad médica.",
                },
                "texto_original": {
                    "type": "string",
                    "description": "Texto original completo del mensaje del viajero.",
                },
            },
            "required": ["descripcion", "texto_original"],
        },
    },
    {
        "name": "generar_respuesta",
        "description": (
            "Genera el mensaje de respuesta final -empático y en español- "
            "para el viajero o prestador, con contenido diferenciado según "
            "la categoría. Es siempre el último paso del flujo: llamala una "
            "sola vez, después de clasificar (y de registrar_caso si "
            "corresponde)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "categoria": {
                    "type": "string",
                    "enum": ["SOLICITUD_NUEVA", "SEGUIMIENTO", "PRESTADOR", "OTRO"],
                    "description": "Categoría detectada por clasificar_mensaje.",
                },
                "datos": {
                    "type": "object",
                    "description": (
                        "Datos para personalizar la respuesta: nombre_viajero, "
                        "id_caso (si se registró uno nuevo), numero_caso_mencionado "
                        "(si el usuario citó un número de caso existente)."
                    ),
                    "properties": {
                        "nombre_viajero": {"type": "string"},
                        "id_caso": {"type": "string"},
                        "numero_caso_mencionado": {"type": "string"},
                    },
                },
            },
            "required": ["categoria"],
        },
    },
]


# ---------------------------------------------------------------------------
# clasificar_mensaje
# ---------------------------------------------------------------------------
# Clasificación real vía un llamado a Claude con salida estructurada
# (output_config.format / json_schema), no reglas de palabras clave.
# Ver README.md > "Decisiones de diseño" para el razonamiento detrás de esto.

_CLASIFICACION_SYSTEM = """\
Sos un clasificador experto de mensajes entrantes para Coris Latinoamérica, \
una compañía de asistencia al viajero que opera en Argentina, Colombia, \
Perú, Chile, Uruguay y Paraguay.

Clasificá el mensaje del usuario en EXACTAMENTE una de estas categorías:

- SOLICITUD_NUEVA: el viajero reporta una emergencia o necesidad médica \
por primera vez (no menciona un caso previo).
- SEGUIMIENTO: es una consulta sobre un caso ya abierto (menciona número \
de caso, una fecha previa, o pregunta por el estado de un trámite en curso).
- PRESTADOR: el mensaje lo envía un médico, hospital o clínica consultando \
por cobertura, autorización o un paciente derivado por la compañía.
- OTRO: cualquier mensaje que no encaje en las anteriores (consultas \
comerciales, información general, contratación de planes, etc.)

Devolvé también una confianza entre 0 y 1, y un resumen de una sola línea \
en español del contenido del mensaje."""

_CLASIFICACION_SCHEMA = {
    "type": "object",
    "properties": {
        "categoria": {
            "type": "string",
            "enum": ["SOLICITUD_NUEVA", "SEGUIMIENTO", "PRESTADOR", "OTRO"],
        },
        "confianza": {"type": "number"},
        "resumen": {"type": "string"},
    },
    "required": ["categoria", "confianza", "resumen"],
    "additionalProperties": False,
}


def clasificar_mensaje(texto: str) -> dict:
    """Clasifica `texto` usando un llamado dedicado a Claude con JSON Schema.

    Se implementa como su propio llamado a la API (en vez de reglas
    hardcodeadas) para que la clasificación use comprensión semántica real
    del mensaje, y para que la tool quede desacoplada del agente
    orquestador: podría reemplazarse mañana por un clasificador propio sin
    tocar el loop principal.
    """
    client = _get_client()
    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system=_CLASIFICACION_SYSTEM,
        messages=[{"role": "user", "content": texto}],
        output_config={
            "format": {"type": "json_schema", "schema": _CLASIFICACION_SCHEMA}
        },
    )
    texto_json = next(b.text for b in response.content if b.type == "text")
    resultado = json.loads(texto_json)
    resultado["texto_original"] = texto
    return resultado


# ---------------------------------------------------------------------------
# registrar_caso
# ---------------------------------------------------------------------------

def _cargar_casos() -> list:
    if os.path.exists(CASOS_FILE):
        with open(CASOS_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []


def _guardar_casos(casos: list) -> None:
    with open(CASOS_FILE, "w", encoding="utf-8") as f:
        json.dump(casos, f, ensure_ascii=False, indent=2)


def registrar_caso(datos: dict) -> dict:
    """Simula el alta de un caso nuevo: genera un ID y lo persiste en JSON."""
    casos = _cargar_casos()

    anio = datetime.datetime.now().year
    numero = random.randint(1000, 9999)
    id_caso = f"COR-{anio}-{numero:04d}"
    # Evita colisiones improbables contra casos ya guardados en el archivo.
    ids_existentes = {c.get("id_caso") for c in casos}
    while id_caso in ids_existentes:
        numero = random.randint(1000, 9999)
        id_caso = f"COR-{anio}-{numero:04d}"

    caso = {
        "id_caso": id_caso,
        "fecha_registro": datetime.datetime.now().isoformat(timespec="seconds"),
        "estado": "ABIERTO",
        "nombre_viajero": datos.get("nombre_viajero"),
        "ubicacion": datos.get("ubicacion"),
        "descripcion": datos.get("descripcion"),
        "texto_original": datos.get("texto_original"),
    }

    casos.append(caso)
    _guardar_casos(casos)
    return caso


# ---------------------------------------------------------------------------
# generar_respuesta
# ---------------------------------------------------------------------------
# Generación por plantillas (no un llamado adicional a Claude): la respuesta
# al usuario es texto de cara al cliente con requisitos de contenido
# puntuales (confirmar recepción, X minutos, etc.), así que se prioriza
# consistencia y control determinístico del tono sobre variabilidad.

def generar_respuesta(categoria: str, datos: dict = None) -> dict:
    datos = datos or {}
    nombre = datos.get("nombre_viajero")
    saludo = f"Hola {nombre}, " if nombre else "Hola, "

    if categoria == "SOLICITUD_NUEVA":
        id_caso = datos.get("id_caso")
        referencia = f" Tu número de caso es {id_caso}." if id_caso else ""
        mensaje = (
            f"{saludo}lamentamos mucho lo que estás atravesando. "
            f"Ya registramos tu solicitud y estamos coordinando tu atención "
            f"médica.{referencia} Un asesor de Coris se va a comunicar con "
            f"vos dentro de los próximos 15 minutos para confirmar los "
            f"detalles y coordinar el prestador más cercano. Si tu "
            f"situación empeora mientras tanto, contactanos de inmediato "
            f"por este mismo medio."
        )
    elif categoria == "SEGUIMIENTO":
        numero_caso = datos.get("numero_caso_mencionado")
        referencia = f" del caso {numero_caso}" if numero_caso else ""
        mensaje = (
            f"{saludo}gracias por tu paciencia. Ya estamos revisando el "
            f"estado{referencia} y en breve te compartimos una actualización "
            f"con el detalle de la coordinación médica. Si necesitás algo "
            f"urgente mientras tanto, escribinos por este mismo medio."
        )
    elif categoria == "PRESTADOR":
        mensaje = (
            f"{saludo}gracias por comunicarte con Coris Latinoamérica. "
            f"Estamos verificando la cobertura y la autorización "
            f"correspondiente para el paciente indicado, y te confirmamos "
            f"en breve los detalles de la autorización. Ante cualquier "
            f"urgencia, contactanos a nuestra línea de asistencia médica."
        )
    else:  # OTRO
        mensaje = (
            f"{saludo}gracias por escribirnos. Tu mensaje no corresponde a "
            f"una emergencia de asistencia en curso, así que lo derivamos a "
            f"nuestro equipo comercial, que se va a contactar con vos a la "
            f"brevedad para brindarte toda la información que necesitás."
        )

    return {"categoria": categoria, "mensaje": mensaje}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def ejecutar_tool(nombre: str, tool_input: dict) -> dict:
    """Ejecuta la tool solicitada por Claude y devuelve su resultado (dict)."""
    if nombre == "clasificar_mensaje":
        return clasificar_mensaje(tool_input["texto"])
    if nombre == "registrar_caso":
        return registrar_caso(tool_input)
    if nombre == "generar_respuesta":
        return generar_respuesta(tool_input["categoria"], tool_input.get("datos"))
    raise ValueError(f"Tool desconocida: {nombre}")
