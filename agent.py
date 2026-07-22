"""
Agente de clasificación y primera respuesta - Coris Latinoamérica.

Recibe mensajes de texto simulando solicitudes entrantes de viajeros o
prestadores, los clasifica mediante Claude API (Tool Use) y ejecuta la
acción correspondiente: registrar un caso nuevo y/o generar la respuesta
de primera línea.

Uso:
    python agent.py
"""

import json
import os
import sys

import anthropic
from dotenv import load_dotenv

from tools import TOOLS, ejecutar_tool

load_dotenv()

MODEL = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")
MAX_TURNOS = 6  # límite de vueltas del loop por mensaje, evita loops infinitos

SYSTEM_PROMPT = """\
Sos el agente de clasificación y primera respuesta del equipo de \
Operaciones de Coris Latinoamérica, una compañía de asistencia al viajero.

Ante cada mensaje entrante de un viajero o prestador, seguí siempre este \
procedimiento, en orden:

1. Llamá a clasificar_mensaje con el texto completo y literal del mensaje.
2. Según la categoría que te devuelva:
   - Si es SOLICITUD_NUEVA: llamá a registrar_caso con los datos que puedas \
extraer del mensaje (nombre_viajero, ubicacion, descripcion, \
texto_original). No inventes datos que no estén en el mensaje.
   - Si es SEGUIMIENTO, PRESTADOR u OTRO: NO llames a registrar_caso.
3. Llamá siempre, como último paso, a generar_respuesta con la categoria y \
los datos relevantes en "datos" (por ejemplo id_caso si registraste uno \
nuevo, o numero_caso_mencionado si el usuario citó un número de caso \
existente en su mensaje).
4. Una vez que generar_respuesta te devuelva el mensaje final, respondé al \
usuario únicamente con ese mensaje, sin agregar comentarios ni texto extra.

No te saltees pasos ni los repitas innecesariamente."""


def _imprimir_tool_result(resultado: dict) -> None:
    print(f"   -> {json.dumps(resultado, ensure_ascii=False, indent=6)}")


def procesar_mensaje(client: anthropic.Anthropic, texto_mensaje: str) -> str:
    """Corre el loop de Tool Use para un mensaje y devuelve la respuesta final."""
    print("\n" + "=" * 78)
    print("MENSAJE RECIBIDO:")
    print(f"  {texto_mensaje}")
    print("=" * 78)

    messages = [{"role": "user", "content": texto_mensaje}]
    respuesta_final = None

    for _ in range(MAX_TURNOS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            texto_final = "".join(
                b.text for b in response.content if b.type == "text"
            ).strip()
            if texto_final:
                respuesta_final = respuesta_final or texto_final
            break

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue

            print(f"\nTOOL LLAMADA: {block.name}({json.dumps(block.input, ensure_ascii=False)})")
            try:
                resultado = ejecutar_tool(block.name, block.input)
                _imprimir_tool_result(resultado)
                if block.name == "generar_respuesta":
                    respuesta_final = resultado["mensaje"]
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(resultado, ensure_ascii=False),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - se reporta a Claude como error de tool
                print(f"   -> ERROR: {exc}")
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": f"Error ejecutando la tool: {exc}",
                        "is_error": True,
                    }
                )

        messages.append({"role": "user", "content": tool_results})

    print("\nRESPUESTA GENERADA:")
    print(f"  {respuesta_final or '(el agente no generó una respuesta final)'}")
    return respuesta_final


MENSAJES_PRUEBA = [
    "Hola, soy Andrea Gómez, estoy en Madrid y tuve un accidente, necesito atención médica urgente",
    "Llamo por el caso COR-2026-0892 abierto el martes, quería saber si ya tienen al médico asignado",
    "Soy el Dr. Ramírez del Hospital Británico, tengo un paciente de ustedes, código póliza 77421",
    "Quisiera saber los países donde tienen cobertura para contratar un plan familiar",
]


def _ubicacion_casos() -> str:
    return os.environ.get("CASOS_FILE", "casos.json")


def correr_demo(client: anthropic.Anthropic) -> None:
    """Procesa los 4 mensajes de prueba incluidos en el challenge."""
    print("\n>>> VERSIÓN DEMO - procesando los mensajes de prueba del challenge")
    for mensaje in MENSAJES_PRUEBA:
        procesar_mensaje(client, mensaje)

    print("\n" + "=" * 78)
    print(f"Casos registrados en: {_ubicacion_casos()}")
    print("=" * 78)


def correr_interactivo(client: anthropic.Anthropic) -> None:
    """Chat: el usuario escribe mensajes y el agente los clasifica y responde."""
    print("\n>>> VERSIÓN INTERACTIVA")
    print("Escribí un mensaje como si fueras un viajero o prestador.")
    print("Para volver al menú, escribí 'salir' (o dejá la línea vacía).")

    while True:
        try:
            mensaje = input("\nTu mensaje > ").strip()
        except EOFError:
            break

        if mensaje.lower() in ("", "salir", "exit", "quit"):
            break

        procesar_mensaje(client, mensaje)

    print(f"\nCasos registrados en: {_ubicacion_casos()}")


def elegir_version() -> str:
    """Muestra el menú de inicio y devuelve 'demo', 'interactivo' o 'salir'."""
    print("=" * 78)
    print("AGENTE DE CLASIFICACIÓN - Coris Latinoamérica")
    print("=" * 78)
    print("Seleccioná una versión:")
    print("  1) Demo         - procesa los 4 mensajes de prueba del challenge")
    print("  2) Interactiva  - escribí tus propios mensajes y se clasifican")
    print("  3) Salir")

    while True:
        try:
            opcion = input("\nOpción [1/2/3] > ").strip()
        except EOFError:
            return "salir"

        if opcion in ("1", "demo"):
            return "demo"
        if opcion in ("2", "interactivo", "interactiva"):
            return "interactivo"
        if opcion in ("3", "salir", "exit", "quit"):
            return "salir"
        print("Opción inválida. Ingresá 1, 2 o 3.")


def main() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ERROR: no se encontró la variable de entorno ANTHROPIC_API_KEY.\n"
            "Configurala antes de correr el agente (ver README.md)."
        )
        sys.exit(1)

    client = anthropic.Anthropic()

    while True:
        version = elegir_version()
        if version == "demo":
            correr_demo(client)
        elif version == "interactivo":
            correr_interactivo(client)
        else:  # salir
            print("\nHasta luego.")
            break


if __name__ == "__main__":
    main()
