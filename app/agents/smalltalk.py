"""Small talk: greetings, thanks, goodbyes, 'who are you' and 'what can you do'.

These need no documents, so they must never go through retrieval (which would answer 'I could not verify it' to 'hi').
Detection is deliberately strict: the WHOLE message has to be small talk. 'hi, what is the leave policy?' is a real question and still
goes to the document agents. Replies are fixed templates, not model output, so they cannot invent facts; they only state what is true
about this workspace (how many documents are indexed). English, Hindi and Hinglish (Roman Hindi) are supported."""
from __future__ import annotations

import re
from typing import Optional

from ..intel.language import detect_language

_PUNCT = re.compile(r"[^\wऀ-ॿ\s']+")
_REPEAT = re.compile(r"(.)\1{2,}")           # 'hiiii' -> 'hii', 'heyyy' -> 'heyy'

GREETING = {"hi", "hii", "hey", "heyy", "hello", "helo", "hlo", "hallo", "yo", "hola", "namaste", "namaskar", "pranam", "salaam", "salam", "नमस्ते", "नमस्कार", "हेलो", "हाय", "हैलो", "सलाम"}
_GREETING_PHRASES = ("good morning", "good afternoon", "good evening", "good night", "gm", "suprabhat", "शुभ प्रभात", "सुप्रभात", "शुभ रात्रि")
HOW_ARE_YOU = ("how are you", "how r u", "how are u", "hows it going", "how is it going", "whats up", "wassup", "sup", "kaise ho", "kaisa hai", "kaise hain", "kya haal hai",
               "kya haal", "kaisi ho", "aap kaise ho", "aap kaise hain", "कैसे हो", "कैसे हैं", "क्या हाल है", "आप कैसे हैं", "आप कैसे हो")
THANKS = ("thanks", "thank you", "thankyou", "thx", "ty", "thanks a lot", "many thanks", "shukriya", "dhanyavad", "dhanyawad", "dhanyabad", "shukria", "धन्यवाद", "शुक्रिया", "थैंक्स", "थैंक यू")
BYE = ("bye", "goodbye", "good bye", "see you", "see ya", "take care", "alvida", "tata", "ok bye", "okay bye", "phir milte hain", "अलविदा", "फिर मिलेंगे", "बाय")
IDENTITY = ("who are you", "what are you", "who r u", "tum kaun ho", "aap kaun ho", "aap kaun hain", "tum kon ho", "kaun ho tum", "तुम कौन हो", "आप कौन हैं", "आप कौन हो")
CAPABILITIES = ("what can you do", "what do you do", "how can you help", "how can you help me", "help", "help me", "can you help me", "how do you work", "how to use", "how to use this",
                "kya kar sakte ho", "tum kya kar sakte ho", "aap kya kar sakte ho", "kya kar sakte hain", "madad", "madad karo", "meri madad karo", "help karo", "मदद", "मदद करो", "आप क्या कर सकते हैं", "तुम क्या कर सकते हो")
ACK = ("ok", "okay", "k", "kk", "cool", "nice", "great", "good", "fine", "alright", "theek hai", "thik hai", "accha", "achha", "acha", "ठीक है", "अच्छा")
FILLER = {"there", "bot", "assistant", "ji", "bhai", "dost", "friend", "sir", "madam", "please", "pls", "plz", "again", "so", "much", "very", "a", "lot", "you", "u", "ho", "hai", "aap", "tum", "to", "toh", "kya", "mujhe", "ek"}
HINGLISH_MARKERS = {"namaste", "namaskar", "pranam", "kaise", "kaisa", "kaisi", "haal", "shukriya", "dhanyavad", "dhanyawad", "dhanyabad", "alvida", "kaun", "kon", "kar", "sakte", "madad", "theek", "thik", "accha", "achha", "acha", "karo", "hain", "ho", "hai", "bhai", "dost", "ji", "tata", "milte", "phir"}


def _norm(text: str) -> str:
    t = _PUNCT.sub(" ", text.lower())
    t = _REPEAT.sub(lambda m: m.group(1) * 2, t)
    return re.sub(r"\s+", " ", t).strip()


def _only_phrase(t: str, phrases: tuple[str, ...]) -> bool:
    """True when the message is exactly one of the phrases, optionally with harmless filler words around it ('thanks a lot bhai')."""
    for p in sorted(phrases, key=len, reverse=True):
        if t == p:
            return True
        if p in t:
            rest = t.replace(p, " ").split()
            if len(rest) <= 3 and all(w in FILLER or w in GREETING for w in rest):
                return True
    return False


def detect(question: str) -> Optional[str]:
    """-> 'greeting' | 'how_are_you' | 'thanks' | 'bye' | 'identity' | 'capabilities' | 'ack' | None. None for anything that might be a real question."""
    t = _norm(question)
    if not t or len(t.split()) > 8 or "?" in question and len(t.split()) > 6:
        return None
    words = t.split()
    # order matters: a message that thanks AND says bye is 'thanks'; a greeting plus 'how are you' is 'how_are_you'
    if _only_phrase(t, THANKS):
        return "thanks"
    if _only_phrase(t, BYE):
        return "bye"
    if _only_phrase(t, IDENTITY):
        return "identity"
    if _only_phrase(t, CAPABILITIES):
        return "capabilities"
    greeting_words = [w for w in words if w in GREETING]
    stripped = [w for w in words if w not in GREETING]
    rest = " ".join(stripped)
    if rest and _only_phrase(rest, HOW_ARE_YOU):
        return "how_are_you"
    if _only_phrase(t, HOW_ARE_YOU):
        return "how_are_you"
    if greeting_words and all(w in GREETING or w in FILLER for w in words):
        return "greeting"
    if any(t == p or t.startswith(p + " ") and len(words) <= len(p.split()) + 2 for p in _GREETING_PHRASES):
        return "greeting"
    if t in ACK:
        return "ack"
    return None


def style(question: str) -> str:
    """'hi' (Devanagari), 'hinglish' (Roman Hindi) or 'en'."""
    if detect_language(question) == "hi":
        return "hi"
    words = set(_norm(question).split())
    return "hinglish" if words & HINGLISH_MARKERS else "en"


def _docs(n: int, lang: str) -> str:
    if lang == "hi":
        return f"आपके workspace में {n} document{'s' if n != 1 else ''} हैं। उनके बारे में कुछ भी पूछिए।" if n else "अभी कोई document नहीं है। Library में file upload कीजिए, फिर उसके बारे में सवाल पूछिए।"
    if lang == "hinglish":
        return f"Aapke workspace mein {n} document{'s' if n != 1 else ''} hain. Unke baare mein kuch bhi poochiye." if n else "Abhi koi document nahi hai. Library mein file upload kijiye, phir uske baare mein sawal poochiye."
    return f"Your workspace has {n} document{'s' if n != 1 else ''} indexed. Ask me anything about {'them' if n != 1 else 'it'}." if n else "No documents are indexed yet. Upload a file in the Library, then ask questions about it."


REPLIES = {
    "greeting": {"en": "Hello! I'm your knowledge assistant. I answer questions from your uploaded documents, with sources.",
                 "hinglish": "Namaste! Main aapka knowledge assistant hoon. Main aapke upload kiye documents se sources ke saath jawab deta hoon.",
                 "hi": "नमस्ते! मैं आपका knowledge assistant हूँ। मैं आपके upload किए documents से, sources के साथ, जवाब देता हूँ।"},
    "how_are_you": {"en": "I'm doing well, thank you! Ready to help with your documents.",
                    "hinglish": "Main theek hoon, shukriya! Aapke documents mein madad ke liye taiyaar hoon.",
                    "hi": "मैं ठीक हूँ, धन्यवाद! आपके documents में मदद के लिए तैयार हूँ।"},
    "thanks": {"en": "You're welcome! Ask me anything else about your documents.", "hinglish": "Koi baat nahi! Documents ke baare mein aur kuch poochna ho to bataiye.", "hi": "कोई बात नहीं! Documents के बारे में और कुछ पूछना हो तो बताइए।"},
    "bye": {"en": "Goodbye! Come back any time.", "hinglish": "Alvida! Jab marzi wapas aaiye.", "hi": "अलविदा! जब मन हो वापस आइए।"},
    "ack": {"en": "Got it. What would you like to know?", "hinglish": "Theek hai. Aap kya jaanna chahte hain?", "hi": "ठीक है। आप क्या जानना चाहते हैं?"},
    "identity": {"en": "I'm the Multi-Agent Knowledge Assistant. I search your uploaded documents, tables and spreadsheets, and answer with citations.",
                 "hinglish": "Main Multi-Agent Knowledge Assistant hoon. Main aapke upload kiye documents, tables aur spreadsheets mein dhoondhta hoon aur citations ke saath jawab deta hoon.",
                 "hi": "मैं Multi-Agent Knowledge Assistant हूँ। मैं आपके upload किए documents, tables और spreadsheets में खोजता हूँ और citations के साथ जवाब देता हूँ।"},
}
CAPS = {
    "en": "I can: answer questions with citations; find exact words and count them; summarise documents; compare two documents or versions; analyse CSV/Excel tables and draw charts; and build PDF/Word/Excel reports.",
    "hinglish": "Main yeh kar sakta hoon: citations ke saath sawalon ke jawab; exact shabd dhoondhna aur ginna; documents ka summary; do documents ya versions ki tulna; CSV/Excel tables ka analysis aur charts; aur PDF/Word/Excel reports.",
    "hi": "मैं यह कर सकता हूँ: citations के साथ सवालों के जवाब; exact शब्द खोजना और गिनना; documents का सारांश; दो documents या versions की तुलना; CSV/Excel tables का विश्लेषण और charts; और PDF/Word/Excel reports।",
}


def reply(kind: str, question: str, n_documents: int) -> dict:
    """-> {'answer', 'language'}. Fixed text (no model, no invented facts); mentions how many documents are indexed for greetings, identity and help."""
    lang = style(question)
    text = REPLIES.get(kind, REPLIES["greeting"])[lang] if kind != "capabilities" else CAPS[lang]
    if kind in ("greeting", "how_are_you", "identity", "capabilities", "ack"):
        text += " " + _docs(n_documents, lang)
    return {"answer": text, "language": "hi" if lang == "hi" else "en"}
