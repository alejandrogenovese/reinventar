"""Catálogo oficial sintético con la forma de sessions_full.json (catalog.awsevents.com/api/sessions).

Cubre: repeticiones (-R), charla sponsoreada, homónimos (dos "David Victoria" con distinto userRef) y renombre de código.
"""


def persona(ref: str, nombre: str, empresa: str, rol: str = "Internal Speaker", orden: float = 0.0,
            cargo: str = "Solutions Architect") -> dict:
    return {"userRef": ref, "speakerId": f"{ref}_fixture", "globalFullName": nombre, "fullName": nombre,
            "globalCompany": empresa, "companyName": empresa, "globalJobtitle": cargo, "roles": rol,
            "displayorder": orden}


def item(code: str, session_id: str, time_id: str, *, titulo: str = "Charla de prueba", tipo: str = "Breakout session",
         fecha: str = "2026-12-01", inicio: str = "10:00", fin: str = "11:00",
         room: str = "MGM Grand | Level 3 | Premier 311", participantes: list | None = None,
         attrs: list | None = None, modified: str = "2026-11-06T20:31:24Z") -> dict:
    return {
        "code": code, "sessionID": session_id, "title": titulo, "type": tipo, "abstract": f"Resumen de {titulo}.",
        "length": 60.0, "modified": modified,
        "times": [{"date": fecha, "startTime": inicio, "endTime": fin, "room": room, "capacity": "78",
                   "sessionID": session_id, "sessionTimeID": time_id}],
        "attributevalues": [{"attribute": a, "value": v} for a, v in (attrs or [])],
        "participants": participantes or [],
    }


ANA = persona("u-ana", "Ana Pérez", "AWS", orden=0)
BOB = persona("u-bob", "Bob Smith (Acme)", "Acme Bank", rol="External Speaker", orden=1, cargo="CTO")
CARLA = persona("u-carla", "Carla Gómez", "Datadog", rol="Sponsor Speaker")
DAVID_AMAZON = persona("u-david-1", "David Victoria", "Amazon")
DAVID_CAYLENT = persona("u-david-2", "David Victoria", "Caylent")
EVA = persona("u-eva", "Eva Ruiz", "AWS")


def catalogo(*items: dict) -> dict:
    return {"sectionList": [{"items": list(items)}]}


def catalogo_v1() -> dict:
    return catalogo(
        item("ARC100", "s-arc100", "t-arc100", titulo="Arquitectura", participantes=[BOB, ANA],
             attrs=[("Level", "300 – Advanced"), ("Topic", "Architecture"), ("Topic", "Serverless"),
                    ("Area of Interest", "Generative AI"), ("Area of Interest", "Cost"), ("Role", "Developer"),
                    ("Industry", "Financial Services"), ("Hide Speakers?", "No"), ("Walk up only session", "Walk up only")]),
        item("ARC100-R", "s-arc100r", "t-arc100r", titulo="Arquitectura", fecha="2026-12-02", inicio="14:00",
             fin="15:00", room="Venetian | Level 2", participantes=[ANA, BOB],
             attrs=[("Walk up only session", "Walk up only")], modified="2026-11-01T10:00:00Z"),
        item("SEC200-S", "s-sec200", "t-sec200", titulo="Seguridad sponsoreada", participantes=[CARLA],
             attrs=[("Session Appendices", "Sponsored"), ("Hide Speakers?", "Yes")]),
        item("DEV300", "s-dev300", "t-dev300", titulo="Charla de David en Amazon", participantes=[DAVID_AMAZON, EVA]),
        item("COM400", "s-com400", "t-com400", titulo="Charla de David en Caylent", participantes=[DAVID_CAYLENT]),
        item("PEX321", "s-pex", "t-pex", titulo="Charla que AWS renombra", participantes=[EVA]),
    )


def catalogo_v2() -> dict:
    """v1 con PEX321 renombrada a PEX218 (mismo sessionTimeID) y SEC200-S dada de baja."""
    items = [i for i in catalogo_v1()["sectionList"][0]["items"] if i["code"] not in ("PEX321", "SEC200-S")]
    items.append(item("PEX218", "s-pex", "t-pex", titulo="Charla que AWS renombra", participantes=[EVA]))
    return catalogo(*items)
