"""Fast command engine — deterministic Hindi / Hinglish / English commands
that run instantly without the local LLM (and keep working if Ollama is off).

parse(text) -> Command | None
respond(cmd, result, lang) -> what Friday should say, in the user's language
"""
import re
from dataclasses import dataclass, field
from datetime import datetime

from .lang import detect_language


@dataclass
class Command:
    tool: str                      # toolbox tool name, or "_goodbye" / "_sleep" / "_stop"
    args: dict = field(default_factory=dict)


_PUNCT = re.compile(r"(?<!\w)\.|\.(?!\w)|[,!?।॥\"“”‘’]+")
_LEAD = re.compile(r"^(?:(?:hey|ok|okay|please|plz|zara|jara|ज़रा|जरा|कृपया|friday|फ्राइडे|sir|सर)\s+)+", re.I)
_TRAIL = re.compile(r"(?:\s+(?:please|plz|na|ना|जी|ji|sir|सर|yaar|यार|now|abhi|अभी))+$", re.I)

# Multi-step requests go to the LLM.
_COMPOUND = re.compile(r"\b(and then|and|then|after that|aur|phir|fir)\b|\s(और|फिर|उसके बाद)\s", re.I)

N = r"(\d{1,3})"


def normalise(text: str) -> str:
    t = _PUNCT.sub(" ", text or "")
    t = t.replace("'", "")
    t = re.sub(r"\s+", " ", t).strip().lower()
    t = _LEAD.sub("", t)
    t = _TRAIL.sub("", t)
    return t.strip()


# --- word lists -----------------------------------------------------------
OPEN_HI = r"(?:खोलो|खोल दो|खोल दीजिए|खोलिए|खोलें|ओपन करो|ओपन कर दो|ओपन कीजिए|ओपन|चालू करो|चालू कर दो|स्टार्ट करो|लॉन्च करो)"
OPEN_RO = r"(?:kholo|khol do|khol dijiye|kholiye|open karo|open kar do|open kardo|open kijiye|chalu karo|chalu kar do|start karo|launch karo)"
CLOSE_HI = r"(?:बंद करो|बंद कर दो|बंद कीजिए|बन्द करो|बन्द कर दो|क्लोज करो|क्लोज़ करो|क्लोज कर दो|हटाओ)"
CLOSE_RO = r"(?:band karo|band kar do|band kardo|bandh karo|bandh kar do|close karo|close kar do|band kijiye)"
SEARCH_HI = r"(?:सर्च करो|सर्च कर दो|सर्च कीजिए|खोजो|खोज दो|ढूंढो|ढूँढो|ढूंढ दो|ढूँढ दो|सर्च)"
SEARCH_RO = r"(?:search karo|search kar do|search kardo|dhundo|dhundho|dhoondo|khojo|search)"
PLAY_HI = r"(?:चलाओ|चला दो|लगाओ|लगा दो|बजाओ|बजा दो|सुनाओ|दिखाओ|प्ले करो|प्ले कर दो)"
PLAY_RO = r"(?:chalao|chala do|lagao|laga do|bajao|baja do|sunao|dikhao|play karo|play kar do)"
VOL_WORD = r"(?:volume|sound|आवाज़|आवाज|वॉल्यूम|वोल्यूम|साउंड|awaaz|awaz|aawaz)"
UP_WORD = r"(?:up|increase|louder|raise|बढ़ाओ|बढ़ा दो|बढाओ|बढ़ाइए|तेज़ करो|तेज करो|तेज़|तेज|ज़्यादा करो|ज्यादा करो|badhao|badha do|tez karo|tez|zyada karo|jyada karo|upar)"
DOWN_WORD = r"(?:down|decrease|lower|quieter|reduce|कम करो|कम कर दो|कम|धीमी करो|धीमा करो|घटाओ|kam karo|kam kar do|kam|dheere karo|dheema karo|ghatao|neeche)"
MUSIC_WORD = r"(?:music|song|गाना|गाने|म्यूजिक|म्यूज़िक|संगीत|gaana|gana|gaane)"

_YT = r"(?:youtube|यूट्यूब|यू ट्यूब)"
_GOOGLE_PREFIX = re.compile(r"^(?:google|गूगल)\s*(?:पे|पर|में|pe|par|mein|me|on)?\s+", re.I)


def _clean_target(s: str) -> str:
    s = re.sub(r"^(?:the|app|application|एप|ऐप)\s+", "", s.strip(), flags=re.I)
    s = re.sub(r"\s+(?:app|application|एप|ऐप|को|ko)$", "", s, flags=re.I)
    return s.strip()


def _only(t: str, vocab: set) -> bool:
    """True if EVERY word is part of the command's vocabulary. Keyword intents
    (battery, screenshot, dark mode…) use this so "how do I take a screenshot on
    Windows" or "my phone battery is dying" go to the LLM instead of firing."""
    words = t.split()
    return bool(words) and len(words) <= 8 and all(w in vocab for w in words)


_FILLER = {"friday", "फ्राइडे", "the", "my", "a", "an", "it", "now", "mac", "macbook", "me", "show", "tell", "check", "get",
           "karo", "kar", "do", "de", "dijiye", "kijiye", "batao", "bataiye", "dikhao", "lo", "le", "ek",
           "करो", "कर", "दो", "दीजिए", "कीजिए", "बताओ", "बताइए", "दिखाओ", "लो", "ले", "एक", "मेरा", "मेरी", "मैक", "का", "की", "है", "ज़रा"}
_BATTERY = _FILLER | {"battery", "level", "status", "percentage", "percent", "left", "life", "what", "whats", "is",
                      "how", "much", "do", "i", "have", "kitni", "kitna", "kitne", "hai", "kya", "kaisi",
                      "बैटरी", "कितनी", "कितना", "कैसी", "लेवल", "स्टेटस", "प्रतिशत", "क्या", "बची", "बचा"}
_STATUS = _FILLER | {"system", "status", "how", "hows", "is", "doing", "cpu", "ram", "usage", "memory", "what", "whats",
                     "kaisa", "haal", "chal", "raha", "ka", "सिस्टम", "स्टेटस", "कैसा", "हाल", "चल", "रहा", "क्या", "सीपीयू", "रैम"}
_SCREENSHOT = _FILLER | {"take", "capture", "grab", "screenshot", "screen", "shot", "स्क्रीनशॉट", "स्क्रीन", "शॉट", "ka", "का"}
_LOCK = _FILLER | {"lock", "screen", "स्क्रीन", "लॉक"}
_DARK = _FILLER | {"toggle", "switch", "turn", "on", "off", "to", "dark", "light", "mode", "enable", "disable", "theme",
                   "change", "डार्क", "लाइट", "मोड", "चालू", "बंद", "थीम", "बदलो"}
_GOODBYE = {"friday", "फ्राइडे", "now", "karo", "kar", "do", "करो", "कर", "दो", "goodbye", "good", "bye", "alvida", "shut", "down", "power", "thanks", "thank", "you", "so", "much",
            "see", "later", "अलविदा", "शट", "डाउन", "बंद", "हो", "जाओ", "धन्यवाद", "शुक्रिया"}

_THE_NONAPP = re.compile(r"^(?:run|start|kill|close|quit|exit)\s+(?:the|a|an|my)\s+(.+)$")
_UP_BY = re.compile(r"\b(?:by|se)\b|से")
_SET_TO = re.compile(r"\b(?:to|at|set)\b|%|\bpercent\b|पर|प्रतिशत")


def parse(text: str) -> Command | None:
    t = normalise(text)
    if not t:
        return None

    # --- session control (always fast, even inside compound sentences) ---
    if re.search(r"\b(goodbye|good bye|bye|shut down|power down|alvida)\b|अलविदा|शट डाउन|बंद हो जाओ", t) \
            and _only(t, _GOODBYE):
        return Command("_goodbye")
    if re.fullmatch(r"(?:stop listening|go to sleep|sleep|so jao|chup ho jao|सो जाओ|सुनना बंद करो|चुप हो जाओ|आराम करो)", t):
        return Command("_sleep")
    if re.fullmatch(r"(?:stop|cancel|never mind|nevermind|ruko|bas|रुको|बस|रहने दो|chhodo|छोड़ो)", t):
        return Command("_stop")

    if _COMPOUND.search(" " + t + " "):
        return None

    # --- time / date / battery / status ---
    if re.search(r"\b(what(?:'?s| is) the time|time (?:is it|kya hai|batao)|current time|kitne baje|samay kya)\b|"
                 r"कितने बजे|टाइम क्या|टाइम बताओ|समय क्या|समय बताओ|वक़्त क्या|वक्त क्या|^time$|^टाइम$|^समय$", t) \
            and len(t.split()) <= 7:
        return Command("get_time")
    if re.search(r"\b(what(?:'?s| is) the date|today'?s date|what day is|date kya|aaj kya date|aaj kaun sa din)\b|"
                 r"तारीख|डेट क्या|डेट बताओ|आज कौन सा दिन|आज क्या दिन|^date$", t) \
            and len(t.split()) <= 7:
        return Command("get_date")
    if re.search(r"battery|बैटरी", t) and _only(t, _BATTERY):
        return Command("get_battery")
    if re.search(r"\b(system status|hows? my mac|how is my mac|mac (?:ka|kaisa) (?:haal|chal)|cpu|ram usage|memory usage)\b|"
                 r"सिस्टम स्टेटस|सिस्टम कैसा|मैक कैसा|मैक का हाल", t) and _only(t, _STATUS):
        return Command("system_status")

    # --- volume ---
    if re.search(VOL_WORD, t):
        if re.search(r"\b(unmute|on karo|chalu)\b|अनम्यूट|चालू", t):
            return Command("mute", {"on": False})
        if re.search(r"\b(mute|band|bandh|off)\b|म्यूट|बंद|बन्द", t):
            return Command("mute", {"on": True})
        m = re.search(N, t)
        up, down = re.search(UP_WORD, t), re.search(DOWN_WORD, t)
        if m:
            n = int(m.group(1))
            # "volume up 20" / "volume 20 kam karo" nudge; "volume 50", "set volume to 50", "आवाज़ 30 पर" set
            if (up or down) and not _SET_TO.search(t):
                return Command("change_volume", {"delta": n if up and not down else -n})
            return Command("set_volume", {"level": n})
        if up:
            return Command("change_volume", {"delta": 10})
        if down:
            return Command("change_volume", {"delta": -10})
    if re.fullmatch(r"(?:(?:make it|turn it|a bit|a little|bit|slightly|thoda|zara)\s+)*(louder|quieter|softer|turn up|turn down|lower|raise)", t):
        return Command("change_volume", {"delta": 10 if re.search(r"louder|up|raise", t) else -10})
    if re.fullmatch(r"(?:turn it|make it)\s+(up|down)", t):
        return Command("change_volume", {"delta": 10 if t.endswith("up") else -10})
    if re.fullmatch(r"(?:mute|म्यूट करो|म्यूट|mute karo)", t) or \
            re.fullmatch(r"mute (?:the |my )?(?:music|sound|audio|speakers|mac)", t):
        return Command("mute", {"on": True})
    if re.fullmatch(r"(?:unmute|अनम्यूट करो|अनम्यूट|unmute karo)", t) or \
            re.fullmatch(r"unmute (?:the |my )?(?:music|sound|audio|speakers|mac)", t):
        return Command("mute", {"on": False})

    # --- media ---
    if re.search(MUSIC_WORD, t) and not re.search(_YT, t):
        if re.search(r"\b(next|skip|agla|agla wala)\b|अगला|अगले|नेक्स्ट", t):
            return Command("media_control", {"command": "next"})
        if re.search(r"\b(previous|pichla|back)\b|पिछला|पिछले", t):
            return Command("media_control", {"command": "previous"})
        if re.search(r"\b(pause|stop|band|ruko|roko)\b|रोको|रोक दो|बंद|पॉज़|पॉज", t):
            return Command("media_control", {"command": "pause"})
        if re.search(r"\b(play|resume|chalao|bajao|lagao)\b|" + PLAY_HI, t):
            return Command("media_control", {"command": "play"})
    if re.fullmatch(r"(?:next song|next track|skip|skip song|skip track)", t):
        return Command("media_control", {"command": "next"})
    if re.fullmatch(r"(?:previous|prev|previous song|previous track|last song|go back)", t):
        return Command("media_control", {"command": "previous"})
    if re.fullmatch(r"(?:pause|pause it|pause playback|पॉज़|पॉज)", t):
        return Command("media_control", {"command": "pause"})
    if re.fullmatch(r"(?:play|resume|resume playback|continue playing|play it)", t):
        return Command("media_control", {"command": "play"})

    # --- YouTube ---
    m = (re.fullmatch(rf"(?:play|search)\s+(.+?)\s+on\s+{_YT}", t)
         or re.fullmatch(rf"{_YT}\s+(?:पे|पर|में|pe|par|mein|me|on)\s+(.+?)(?:\s+(?:{PLAY_HI}|{PLAY_RO}|{SEARCH_HI}|{SEARCH_RO}))?", t)
         or re.fullmatch(rf"(.+?)\s+{_YT}\s+(?:पे|पर|में|pe|par|mein|me)\s+(?:{PLAY_HI}|{PLAY_RO}|{SEARCH_HI}|{SEARCH_RO})", t)
         or re.fullmatch(rf"{_YT}\s+(?:search\s+)?(.+)", t))
    if m and m.group(1).strip() not in ("", "kholo", "खोलो"):
        return Command("youtube_search", {"query": m.group(1).strip()})

    # --- Google search ---
    m = (re.fullmatch(r"(?:search(?: for)?|google|look up)\s+(.+?)(?:\s+on google)?", t)
         or re.fullmatch(rf"(.+?)\s+(?:{SEARCH_HI}|{SEARCH_RO})", t))
    if m:
        q = _GOOGLE_PREFIX.sub("", m.group(1)).strip()
        q = re.sub(r"\s+(?:के बारे में|ke baare mein|ke bare me|ko|को)$", "", q)
        if q:
            return Command("web_search", {"query": q})

    # --- screenshot / lock / dark mode ---
    if re.search(r"screenshot|स्क्रीनशॉट|स्क्रीन शॉट", t) and _only(t.replace("स्क्रीन शॉट", "स्क्रीनशॉट"), _SCREENSHOT):
        return Command("take_screenshot")
    if re.search(r"\block (?:the )?screen\b|screen lock|स्क्रीन लॉक|लॉक करो", t) and _only(t, _LOCK):
        return Command("lock_screen")
    if re.search(r"dark mode|डार्क मोड|light mode|लाइट मोड", t) and _only(t, _DARK):
        return Command("toggle_dark_mode")

    # "run the tests", "close the door", "kill the lights": not apps unless we know the name
    mt = _THE_NONAPP.match(t)
    if mt:
        from .actions import APP_ALIASES
        if mt.group(1).strip() not in APP_ALIASES:
            return None

    # --- close app ---
    m = (re.fullmatch(r"(?:close|quit|exit|kill)\s+(.+)", t)
         or re.fullmatch(rf"(.+?)\s+(?:{CLOSE_HI}|{CLOSE_RO})", t))
    if m:
        return Command("quit_app", {"name": _clean_target(m.group(1))})

    # --- open app / folder ---
    m = (re.fullmatch(r"(?:open|launch|start|run)\s+(.+)", t)
         or re.fullmatch(rf"(.+?)\s+(?:{OPEN_HI}|{OPEN_RO})", t))
    if m:
        target = _clean_target(m.group(1))
        from .actions import FOLDERS
        if target.lower() in FOLDERS:
            return Command("open_path", {"path": target.lower()})
        if re.search(r"\.(com|in|org|net|io|dev)\b", target):
            return Command("open_url", {"url": target.replace(" ", "")})
        return Command("open_app", {"name": target})

    return None


# --- localized replies ------------------------------------------------------
_WEEKDAYS_HI = ["सोमवार", "मंगलवार", "बुधवार", "गुरुवार", "शुक्रवार", "शनिवार", "रविवार"]
_MONTHS_HI = ["जनवरी", "फ़रवरी", "मार्च", "अप्रैल", "मई", "जून", "जुलाई", "अगस्त",
              "सितंबर", "अक्टूबर", "नवंबर", "दिसंबर"]
_BATT_HI = {"charging": "चार्ज हो रही है", "discharging": "चार्जर नहीं लगा है",
            "charged": "पूरी चार्ज है", "ac attached": "चार्जर लगा है", "finishing charge": "लगभग चार्ज हो गई है"}


def _failed(result: str) -> bool:
    return bool(re.match(r"^(couldn't|i couldn't|invalid|unknown|no files|.* failed|.*doesn't exist)", result, re.I))


def respond(cmd: Command, result: str, lang: str) -> str:
    """Turn an action result into Friday's spoken reply in `lang`."""
    if lang != "hi":
        return result
    now = datetime.now()
    a = cmd.args
    if _failed(result):
        if cmd.tool == "open_app":
            return f"माफ़ कीजिए, {a.get('name')} नाम का ऐप नहीं मिला।"
        return "माफ़ कीजिए, ये नहीं हो पाया।"
    if cmd.tool == "get_time":
        h = now.hour % 12 or 12
        return f"अभी {h} बजकर {now.minute} मिनट हुए हैं।" if now.minute else f"अभी ठीक {h} बजे हैं।"
    if cmd.tool == "get_date":
        return f"आज {_WEEKDAYS_HI[now.weekday()]}, {now.day} {_MONTHS_HI[now.month - 1]} {now.year} है।"
    if cmd.tool == "get_battery":
        m = re.search(r"(\d+) percent, (.+?)\.?$", result)
        if not m:
            return "इस मैक में बैटरी नहीं दिख रही।"
        state = _BATT_HI.get(m.group(2).lower(), "")
        return f"बैटरी {m.group(1)} प्रतिशत है" + (f", {state}।" if state else "।")
    if cmd.tool == "system_status":
        cpu = re.search(r"CPU (\d+)", result)
        mem = re.search(r"memory (\d+)", result)
        disk = re.search(r"(\d+) gigabytes free", result)
        parts = []
        if cpu: parts.append(f"सीपीयू {cpu.group(1)} प्रतिशत")
        if mem: parts.append(f"मेमोरी {mem.group(1)} प्रतिशत भरी है")
        if disk: parts.append(f"डिस्क में {disk.group(1)} जीबी खाली है")
        return "सिस्टम ठीक चल रहा है — " + ", ".join(parts) + "।"
    if cmd.tool == "open_app":
        app = re.sub(r"^Opened |\.$", "", result)
        return f"{app} खोल दिया।"
    if cmd.tool in ("open_path", "open_url"):
        return "खोल दिया।"
    if cmd.tool == "quit_app":
        return f"{a.get('name')} बंद कर दिया।"
    if cmd.tool in ("set_volume", "change_volume"):
        m = re.search(r"(\d+) percent", result)
        return f"आवाज़ {m.group(1)} प्रतिशत कर दी।" if m else "आवाज़ बदल दी।"
    if cmd.tool == "mute":
        return "आवाज़ बंद कर दी।" if a.get("on") else "आवाज़ वापस चालू कर दी।"
    if cmd.tool == "media_control":
        return {"next": "अगला गाना।", "previous": "पिछला गाना।", "pause": "गाना रोक दिया।"}.get(a["command"], "गाना चला दिया।")
    if cmd.tool == "web_search":
        return f"गूगल पर {a['query']} खोज दिया।"
    if cmd.tool == "youtube_search":
        return f"यूट्यूब पर {a['query']} लगा दिया।"
    if cmd.tool == "take_screenshot":
        return "स्क्रीनशॉट डेस्कटॉप पर सेव कर दिया।"
    if cmd.tool == "lock_screen":
        return "स्क्रीन लॉक कर रहा हूँ।"
    if cmd.tool == "toggle_dark_mode":
        return "थीम बदल दी।"
    return "हो गया।"


def reply_language(text: str, whisper_lang: str) -> str:
    """Prefer what the text looks like; Whisper's guess breaks ties."""
    return "hi" if (whisper_lang == "hi" or detect_language(text) == "hi") else "en"
