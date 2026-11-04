"""Language helpers: decide whether an utterance is Hindi or English so Friday
can answer in the same language with the matching voice.

Handles three cases:
  * Devanagari Hindi         "क्रोम खोलो"
  * Romanised Hindi/Hinglish "chrome kholo", "volume kam karo"
  * English                  "open chrome"
"""
import re

DEVANAGARI = re.compile(r"[ऀ-ॿ]")
ARABIC = re.compile(r"[؀-ۿ]")
WORD = re.compile(r"[a-zA-Zऀ-ॿ]+")

# Common romanised Hindi words. Deliberately excludes words that are also
# ordinary English ("is", "to", "me", "the" ...).
HINGLISH_WORDS = {
    "kya", "kyaa", "hai", "hain", "ho", "hoga", "karo", "kar", "kardo", "karde",
    "karna", "kholo", "khol", "chalao", "chala", "chalu", "band", "bandh", "batao",
    "bata", "bolo", "mujhe", "mera", "meri", "mere", "mujhko", "aap", "aapka",
    "tum", "tumhara", "kaise", "kaisa", "kitna", "kitne", "kitni", "kab", "kahan",
    "kyun", "kyon", "abhi", "aaj", "kal", "nahi", "nahin", "haan", "han", "theek",
    "thik", "accha", "acha", "achha", "bhai", "yaar", "zara", "jara", "thoda",
    "kam", "zyada", "jyada", "badhao", "badha", "ghatao", "dhundo", "dhundho",
    "khojo", "sunao", "bajao", "lagao", "bhejo", "likho", "dikhao", "samay",
    "baje", "waqt", "aur", "ya", "lekin", "matlab", "wala", "wali", "pe", "par",
    "mein", "se", "ka", "ki", "ke", "ko", "ne", "hua", "hui", "raha", "rahi",
    "chahiye", "sakte", "sakta", "shukriya", "dhanyavaad", "dhanyawad", "namaste",
    "alvida", "ruko", "chup", "jao", "jaao", "do", "dijiye", "kijiye", "batayiye",
}
# Words that look Hindi but are common English; only count with other evidence.
_AMBIGUOUS = {"do", "par", "ho", "kal", "han", "ya", "pe", "ne", "se", "ka", "ki", "ke", "ko"}


def detect_language(text: str) -> str:
    """Return 'hi' or 'en' for a piece of text."""
    if not text:
        return "en"
    if DEVANAGARI.search(text) or ARABIC.search(text):
        return "hi"
    words = [w.lower() for w in WORD.findall(text)]
    if not words:
        return "en"
    strong = sum(1 for w in words if w in HINGLISH_WORDS and w not in _AMBIGUOUS)
    weak = sum(1 for w in words if w in _AMBIGUOUS)
    if strong >= 2 or (strong >= 1 and (strong + weak) / len(words) >= 0.25):
        return "hi"
    if strong == 1 and len(words) <= 3:
        return "hi"
    return "en"


def is_hinglish(text: str) -> bool:
    """Romanised Hindi (Latin script) rather than Devanagari."""
    return detect_language(text) == "hi" and not DEVANAGARI.search(text or "")


def pick(lang: str, en: str, hi: str) -> str:
    return hi if lang == "hi" else en
