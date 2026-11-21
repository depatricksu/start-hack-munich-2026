"""Clarifying question (Erik's decision, 21 Nov): when a request misses data we need to price it, ask the customer
once instead of giving up, then quote from their answer.

  ask(tid, mail, fields, missing)  template question in the customer's language, no LLM, status `asked_customer`
  answer(mail)                     ONE gateway call: merge the answer into the form + classify it
                                   provides_info -> price_and_quote (normal path, never asks twice)
                                   decline -> lost   ·   accept / question / other -> needs_human

Only fields we really cannot price without are asked: origin, destination, weight. Everything else has a default.
Open question at the 5U booth: does our question count as the "first reply" of the thread? CLARIFY=0 turns this off.
"""
import json, re

from core import config, db, mailbox
from llm.extract import PRICES, _clip

ASKABLE = ("origin", "destination", "weight_kg")
WORDS = {
    "en": {"origin": "the departure airport in Germany (or the pickup postcode)",
           "destination": "the destination airport or city", "weight_kg": "the total gross weight in kg"},
    "de": {"origin": "den Abflughafen in Deutschland (oder die Abhol-Postleitzahl)",
           "destination": "den Zielflughafen oder die Zielstadt", "weight_kg": "das Gesamtgewicht in kg"},
}
QUESTION = {
    "en": "Hello,\n\nthank you for your request. To give you an exact all-in price, could you please tell us {items}?\n"
          "If you have them, the volume (cbm) or the dimensions of the pieces help as well.\n\n"
          "Best regards\nYour forwarding team",
    "de": "Guten Tag,\n\nvielen Dank für Ihre Anfrage. Damit wir Ihnen einen genauen Gesamtpreis nennen können, "
          "teilen Sie uns bitte noch {items} mit.\nFalls vorhanden, helfen uns auch das Volumen (cbm) oder die Maße "
          "der Packstücke.\n\nMit freundlichen Grüßen\nIhr Forwarding-Team",
}
AND = {"en": " and ", "de": " und "}

SYSTEM = """You help an air freight forwarder. We asked the customer for missing shipment data.
You get the form we have so far (JSON) and the customer's answer. Answer with JSON only:
{
 "kind": "provides_info" if the answer gives shipment data, "accept" if they accept an offer, "decline" if they
         no longer want a quote, "question" if they only ask something, else "other",
 "fields": the form with every value from the answer filled in or corrected. Same keys as the form.
           IATA codes for airports (German origins: FRA MUC DUS HAM STR CGN). Do not calculate, copy numbers as written.
}"""

FORM_KEYS = ("origin", "destination", "pickup_postcode", "weight_kg", "volume_cbm", "pieces", "prefer")


def only_missing(fields, mail):
    """Askable missing fields, or [] if anything else (scope, not-a-request, odd data) stops the request."""
    from shared.rfq import Level, from_fields, validate
    if (fields.get("kind") or "new_request") != "new_request" or fields.get("multi_shipment") or fields.get("unclear"):
        return []
    stops = [i for i in validate(from_fields(fields, mail))
             if i.level in (Level.MISSING, Level.HUMAN) and i.field not in ("message_id", "customer_email")]
    if not stops or any(i.level != Level.MISSING or i.field not in ASKABLE for i in stops):
        return []
    return [i.field for i in stops]


def _lang(fields):
    return "de" if (fields.get("language") or "").lower() == "de" else "en"


def question_text(missing, lang):
    items = [WORDS[lang][m] for m in missing]
    joined = items[0] if len(items) == 1 else ", ".join(items[:-1]) + AND[lang] + items[-1]
    return QUESTION[lang].format(items=joined)


def ask(tid, mail, fields, missing):
    s = db.session(tid)
    body = question_text(missing, _lang(fields))
    subject = s["subject"] if s["subject"].lower().startswith("re:") else "Re: " + s["subject"]
    ok = mailbox.send(s["customer"], subject, body, in_reply_to=mail["id"], thread_id=tid)
    db.update_session(tid, status="asked_customer" if ok else "needs_human",
                      note="asked customer for: %s" % ", ".join(missing) if ok else "could not send our question")
    db.event("clarify_asked" if ok else "clarify_failed", tid, mail["id"], missing=missing)


def _merge_call(fields, text):
    """-> (kind, new fields, usage). One gateway call."""
    form = {k: fields.get(k) for k in FORM_KEYS}
    if config.LLM_FAKE:
        from shared.rfq import extract_rfq
        r = extract_rfq("", text)
        got = {"origin": r.origin, "destination": r.destination, "weight_kg": r.weight_kg,
               "volume_cbm": r.volume_cbm, "pickup_postcode": r.pickup_postcode}
        kind = "provides_info" if any(got.values()) else (
            "decline" if re.search(r"\b(no longer|cancel|not needed|kein bedarf|absage)\b", text, re.I) else "other")
        return kind, {**form, **{k: v for k, v in got.items() if v}}, {"fake": True}
    status, data = mailbox.api("POST", "/v1/gateway/chat/completions", timeout=45, body={
        "model": config.LLM_MODEL, "max_completion_tokens": config.LLM_MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": "FORM:\n%s\n\nANSWER:\n%s" % (json.dumps(form), _clip(text, 2000, 1000))}],
    })
    if status != 200:
        raise RuntimeError("gateway %s: %s" % (status, str(data)[:300]))
    out = json.loads(data["choices"][0]["message"]["content"])
    u = data.get("usage") or {}
    usage = {"model": config.LLM_MODEL, "in": u.get("prompt_tokens"), "out": u.get("completion_tokens")}
    if config.LLM_MODEL in PRICES and usage["in"] is not None:
        pi, po = PRICES[config.LLM_MODEL]
        usage["cost_usd"] = round((usage["in"] * pi + usage["out"] * po) / 1e6, 6)
    return (out.get("kind") or "other"), {**form, **{k: v for k, v in (out.get("fields") or {}).items()
                                                      if k in FORM_KEYS and v not in (None, "", [])}}, usage


def answer(mail):
    from core import main                                    # late import: core.main imports this module
    tid = mail["thread_id"]
    s = db.session(tid)
    if mail["sender"] != (s["customer"] or "").lower():
        return main.needs_human(tid, mail, "answer to our question came from %s, not the customer" % mail["sender"])
    fields = json.loads(s["fields"] or "{}")
    kind, new, usage = _merge_call(fields, mail["body"])
    merged = dict(fields, **new)
    pc = str(merged.get("pickup_postcode") or "")
    if not merged.get("origin") and pc[:2] in main.ZONE_AIRPORT:
        merged["origin"] = main.ZONE_AIRPORT[pc[:2]]
    merged["weight_kg_total"], merged["volume_cbm_total"] = main.shipment(merged)
    cost = (s["llm_cost_usd"] or 0) + (usage.get("cost_usd") or 0)
    db.update_session(tid, fields=merged, llm_cost_usd=cost or None)
    db.event("clarify_answer", tid, mail["id"], verdict=kind, fields={k: merged.get(k) for k in FORM_KEYS}, usage=usage)
    if kind == "decline":
        return db.update_session(tid, status="lost", note="customer declined after our question")
    if kind != "provides_info":
        return main.needs_human(tid, mail, "answer to our question is '%s', not the missing data" % kind)
    db.update_session(tid, status="new")                     # claim_for_sending only allows new / waiting_bids
    main.price_and_quote(tid, mail, merged, asked=True)
