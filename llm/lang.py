"""Which language did the customer write in? Counted in code, $0, no gateway call.

The model once answered an English mail in German because the sender had a German company name and a
"Viele Gruesse" in the sign-off. Here only everyday function words count, so a town name, a company name
or a bilingual sign-off cannot flip the result.

    detect("Hello, could you please quote ...")  -> "en"
    detect("Quote FRA JFK 200 kg")               -> None   (not sure: the caller keeps what it had)
"""
import re

# Only words that are (nearly) unique to one language. Shared ones (in, a, la, de, con, per, die, me) are left out.
WORDS = {
    "en": "the and you your we our please could would can for from with this that have has is are will thanks thank "
          "hello hi dear regards to of need quote cheapest fastest shipment what which how when soon let know be it "
          "option looking forward best kind many greetings price send want".split(),
    "de": "der das und ich wir sie ihr ihre ihren bitte für von nach mit ist sind eine einen einem nicht auch danke "
          "vielen dank hallo guten tag grüße gruesse grüßen sehr geehrte können koennen könnten möchten moechten "
          "benötigen brauchen angebot anfrage sendung günstigste schnellste zum zur bei wie was wann oder uns "
          "freundlichen viele beste über ab bis noch".split(),
    "fr": "le les des du et vous nous votre notre merci bonjour pour avec est sont une au aux cordialement salutations "
          "pouvez pourriez envoi devis prix depuis vers moins cher rapide besoin je il ce cette que qui sur pas "
          "plus bien s'il plaît".split(),
    "it": "il lo gli e voi noi vostro nostro grazie buongiorno salve per è sono una uno della del delle dei al alla "
          "cordiali saluti potete potreste spedizione preventivo prezzo da verso più economico economica veloce "
          "bisogno che di non vorrei vorremmo gentile gentili distinti abbiamo".split(),
    "es": "el los las y usted ustedes nosotros su nuestro gracias hola buenos días para es son una uno del al "
          "saludos cordiales pueden podrían envío cotización precio desde hacia más barato económico rápido "
          "necesitamos necesito que no por favor estimado estimados un atentamente".split(),
}
_SETS = {k: set(v) for k, v in WORDS.items()}
_TOKEN = re.compile(r"[a-zà-öø-ÿß']+")
NAME = {"en": "English", "de": "German", "fr": "French", "it": "Italian", "es": "Spanish",
        # languages we have no own texts for: the mail is written in English and translated before it is sent
        "zh": "Chinese (Simplified)", "ja": "Japanese", "ko": "Korean", "ru": "Russian", "uk": "Ukrainian", "ar": "Arabic",
        "he": "Hebrew", "el": "Greek", "th": "Thai", "hi": "Hindi", "tr": "Turkish", "nl": "Dutch", "pt": "Portuguese",
        "pl": "Polish", "sv": "Swedish", "da": "Danish", "no": "Norwegian", "nb": "Norwegian", "fi": "Finnish",
        "cs": "Czech", "sk": "Slovak", "hu": "Hungarian", "ro": "Romanian", "bg": "Bulgarian", "hr": "Croatian",
        "sr": "Serbian", "sl": "Slovenian", "vi": "Vietnamese", "id": "Indonesian", "ms": "Malay", "ca": "Catalan"}
OWN = ("en", "de", "fr", "it", "es")                 # languages our own sentences and templates exist in

# 5U, 21 Nov 23:12 (round 72, rejected wrong_language): a mail in Chinese with the sign-off "Thanks a lot and have a
# lovely day!" counted as English, because only Latin function words were counted. A script the mail is written in
# beats any word count. Kana first: Japanese also uses Han characters.
_KANA, _HANGUL, _HAN = re.compile(r"[\u3040-\u30ff]"), re.compile(r"[\uac00-\ud7af]"), re.compile(r"[\u4e00-\u9fff]")
_OTHER_SCRIPT = re.compile(r"[\u0370-\u03ff\u0400-\u052f\u0590-\u06ff\u0900-\u097f\u0e00-\u0e7f]")   # Greek, Cyrillic, Hebrew, Arabic, Devanagari, Thai
_LATIN = re.compile(r"[a-zA-Zà-öø-ÿÀ-ÖØ-ßĀ-ž]")


def script(text):
    """-> "ja" | "ko" | "zh" when the mail is written in that script, "other" for another non-Latin script
    (Cyrillic, Arabic, Greek...: the model names the language), None for a Latin-script mail."""
    text = text or ""
    if len(_KANA.findall(text)) >= 4:
        return "ja"
    if len(_HANGUL.findall(text)) >= 4:
        return "ko"
    if len(_HAN.findall(text)) >= 8:
        return "zh"
    other = len(_OTHER_SCRIPT.findall(text))
    return "other" if other >= 12 and other >= 0.3 * (other + len(_LATIN.findall(text))) else None


def scores(text):
    tokens = _TOKEN.findall((text or "").lower())
    return {lang: sum(1 for t in tokens if t in words) for lang, words in _SETS.items()}


def detect(text, min_hits=3):
    """-> "en" | "de" | "fr" | "it" | "es", or None when there are too few hits or no clear winner."""
    sc = script(text)
    if sc:
        return None if sc == "other" else sc
    ranked = sorted(scores(text).items(), key=lambda kv: -kv[1])
    (best, n), (_, second) = ranked[0], ranked[1]
    if n < min_hits or n < second + 2 or n < 1.5 * second:
        return None
    # A Dutch or Polish mail with an English sign-off has three English words too. In a mail that IS in one of our
    # five languages, function words are a large share of all words (real requests: 20 to 45 %); under 12 % it is
    # another language and the model names it.
    if n < 0.12 * len(_TOKEN.findall((text or "").lower())):
        return None
    return best


def hint(lang):
    """One line for the user message of the gateway call, or "" when we are not sure."""
    if lang not in NAME:
        return ""
    return "The customer wrote in %s. Write the reply in %s." % (NAME[lang], NAME[lang])


def name(lang):
    """'zh' -> 'Chinese (Simplified)'; an unknown code is passed on as a code."""
    lang = (lang or "").lower()[:2]
    return NAME.get(lang) or "the language with the ISO 639-1 code '%s'" % lang
