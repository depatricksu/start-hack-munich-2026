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
NAME = {"en": "English", "de": "German", "fr": "French", "it": "Italian", "es": "Spanish"}


def scores(text):
    tokens = _TOKEN.findall((text or "").lower())
    return {lang: sum(1 for t in tokens if t in words) for lang, words in _SETS.items()}


def detect(text, min_hits=3):
    """-> "en" | "de" | "fr" | "it" | "es", or None when there are too few hits or no clear winner."""
    ranked = sorted(scores(text).items(), key=lambda kv: -kv[1])
    (best, n), (_, second) = ranked[0], ranked[1]
    if n < min_hits or n < second + 2 or n < 1.5 * second:
        return None
    return best


def hint(lang):
    """One line for the user message of the gateway call, or "" when we are not sure."""
    if lang not in NAME:
        return ""
    return "The customer wrote in %s. Write the reply in %s." % (NAME[lang], NAME[lang])
