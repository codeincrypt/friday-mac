"""Friday's signature lines in English and Hindi. Kept short — they're spoken."""
import random
from datetime import datetime

from . import config

T_EN = config.USER_TITLE_EN
T_HI = config.USER_TITLE_HI

LINES = {
    "greeting": {
        "en": [f"Good {{part}}, {T_EN}. Friday online and at your service.",
               f"Systems online. Good {{part}}, {T_EN}."],
        "hi": [f"{{part_hi}} {T_HI}। फ्राइडे ऑनलाइन है, बताइए क्या करना है।",
               f"सारे सिस्टम तैयार हैं {T_HI}। {{part_hi}}।"],
    },
    "wake_ack": {
        "en": [f"Yes, {T_EN}?", "At your service.", f"Listening, {T_EN}.", "Go ahead."],
        "hi": [f"जी {T_HI}?", "जी, बताइए।", "हुक्म कीजिए।", f"सुन रहा हूँ {T_HI}।"],
    },
    "working": {
        "en": [f"Right away, {T_EN}.", "On it.", "Consider it done."],
        "hi": ["अभी करता हूँ।", f"जी {T_HI}, हो रहा है।", "बस एक पल।"],
    },
    "done": {
        "en": ["Done.", f"Done, {T_EN}.", "All set."],
        "hi": ["हो गया।", f"हो गया {T_HI}।", "काम पूरा।"],
    },
    "confirm": {
        "en": [f"Just to confirm, {T_EN} — shall I proceed?"],
        "hi": [f"{T_HI}, पक्का कर लूँ — आगे बढ़ूँ?"],
    },
    "cancelled": {
        "en": ["Understood. I've cancelled that.", "Very well, standing down."],
        "hi": ["ठीक है, मैंने रद्द कर दिया।", "समझ गया, नहीं करता।"],
    },
    "error": {
        "en": [f"I'm afraid that didn't work, {T_EN}.", "Apologies, I ran into a problem."],
        "hi": [f"माफ़ कीजिए {T_HI}, कुछ गड़बड़ हो गई।", "क्षमा कीजिए, ये नहीं हो पाया।"],
    },
    "no_brain": {
        "en": ["My reasoning core is offline. Start Ollama and I'll handle that. Simple commands still work."],
        "hi": ["मेरा लोकल दिमाग़ अभी बंद है। ओलामा चालू कीजिए। आसान कमांड अभी भी चलेंगी।"],
    },
    "goodbye": {
        "en": [f"Goodbye, {T_EN}. Powering down.", f"Signing off. Take care, {T_EN}."],
        "hi": [f"अलविदा {T_HI}। सिस्टम बंद कर रहा हूँ।", f"फिर मिलेंगे {T_HI}।"],
    },
    "sleep": {
        "en": [f"Microphone off. Click the orb or press Option J when you need me."],
        "hi": ["माइक बंद कर दिया। ज़रूरत हो तो ऑर्ब पर क्लिक कीजिए या ऑप्शन जे दबाइए।"],
    },
    "not_heard": {
        "en": [f"Sorry, {T_EN}, I didn't catch that."],
        "hi": [f"माफ़ कीजिए {T_HI}, सुनाई नहीं दिया।"],
    },
}


def _part_of_day(hour: int):
    if 5 <= hour < 12:
        return "morning", "सुप्रभात"
    if 12 <= hour < 17:
        return "afternoon", "नमस्कार"
    return "evening", "शुभ संध्या"


def line(key: str, lang: str = "en", **fmt) -> str:
    options = LINES[key]["hi" if lang == "hi" else "en"]
    text = random.choice(options)
    part, part_hi = _part_of_day(datetime.now().hour)
    return text.format(part=part, part_hi=part_hi, **fmt)


def all_static_lines():
    """Every fixed phrase (for pre-caching the neural voice)."""
    for key, langs in LINES.items():
        if key == "greeting":
            continue
        for lang, texts in langs.items():
            for t in texts:
                yield lang, t
