"""Text shown on the cards and in messages (English and Spanish)."""

STRINGS = {
    "en": {
        "win": "VICTORY",
        "loss": "DEFEAT",
        "queue_short": {420: "SoloQ", 440: "Flex", 400: "Normal", 490: "Quickplay", 450: "ARAM"},
        "queue_long": {420: "Ranked Solo/Duo", 440: "Ranked Flex", 400: "Normal Draft",
                       490: "Quickplay", 450: "ARAM"},
        "positions": {"TOP": "TOP", "JUNGLE": "JUNGLE", "MIDDLE": "MID", "BOTTOM": "ADC", "UTILITY": "SUPPORT"},
        "stats": {"cs": "CS · {}/MIN", "damage": "DAMAGE", "gold": "GOLD", "vision": "VISION",
                  "kp": "KILL PART."},
        "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        "date": "{month} {day} · {time}",
        "perfect": "Perfect",
        "game": "game",
        "tiers": {"IRON": "IRON", "BRONZE": "BRONZE", "SILVER": "SILVER", "GOLD": "GOLD", "PLATINUM": "PLATINUM",
                  "EMERALD": "EMERALD", "DIAMOND": "DIAMOND", "MASTER": "MASTER", "GRANDMASTER": "GRANDMASTER",
                  "CHALLENGER": "CHALLENGER"},
        "lp": "{} LP",
    },
    "es": {
        "win": "VICTORIA",
        "loss": "DERROTA",
        "queue_short": {420: "SoloQ", 440: "Flex", 400: "Normal", 490: "Partida rápida", 450: "ARAM"},
        "queue_long": {420: "Clasificatoria Solo/Dúo", 440: "Clasificatoria Flexible", 400: "Normal",
                       490: "Partida rápida", 450: "ARAM"},
        "positions": {"TOP": "TOP", "JUNGLE": "JUNGLA", "MIDDLE": "MID", "BOTTOM": "ADC", "UTILITY": "SUPPORT"},
        "stats": {"cs": "CS · {}/MIN", "damage": "DAÑO", "gold": "ORO", "vision": "VISIÓN",
                  "kp": "P. KILLS"},
        "months": ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"],
        "date": "{day} {month} · {time}",
        "perfect": "Perfecto",
        "game": "partida",
        # Same names as the es_ES League client
        "tiers": {"IRON": "HIERRO", "BRONZE": "BRONCE", "SILVER": "PLATA", "GOLD": "ORO", "PLATINUM": "PLATINO",
                  "EMERALD": "ESMERALDA", "DIAMOND": "DIAMANTE", "MASTER": "MAESTRO", "GRANDMASTER": "GRAN MAESTRO",
                  "CHALLENGER": "ASPIRANTE"},
        "lp": "{} PL",
    },
}

# Data Dragon locale for champion names
LOCALES = {"en": "en_US", "es": "es_ES"}


def get(language: str) -> dict:
    return STRINGS.get(language, STRINGS["en"])
