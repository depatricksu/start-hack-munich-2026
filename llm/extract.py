"""The ONE gateway call per RFQ: read the customer's mail and write the reply text.

The model never does math and never invents a price. It returns:
  - the shipment fields as JSON (code computes weight, volume and price from them)
  - a reply text with placeholders {PRICE} {AIRLINE} {TRANSIT_DAYS}, which code fills in later
"""
import json, re
from core import config, mailbox

SYSTEM = """You work at an air freight forwarder in Germany. Read the customer's email and answer with JSON only:
{
 "origin": IATA code of the German departure airport (FRA, MUC, DUS, HAM, STR, CGN) or null if not given,
 "destination": IATA code of the destination airport or null,
 "pickup_postcode": German postcode if the customer wants pickup at their door, else null,
 "weight_kg": total gross weight in kg if stated as a total, else null,
 "volume_cbm": total volume in cubic meters if stated directly, else null,
 "pieces": [{"count": n, "l_cm": n, "w_cm": n, "h_cm": n, "kg_each": n or null}] if dimensions are given, else [],
 "prefer": "fastest" if the customer asks for the fastest/most urgent option, else "cheapest",
 "language": ISO 639-1 code of the language the customer wrote in ("en", "de", ...),
 "missing": list of fields you could not find,
 "reply": the reply email body
}
Do not calculate anything. Copy numbers as written (convert units to cm and kg only).
The reply: write it in the language of the customer's email, never any other (an English email gets an English reply, a German email a German reply). Greet with the full name exactly as written (for example "Guten Tag K. Weber" or "Hi Anna"); never add Frau, Herr, Mr or Ms. Short, warm, like a real colleague wrote it, no AI phrases.
State one all-in price using exactly the placeholder {PRICE}. Mention {AIRLINE} and {TRANSIT_DAYS} days transit.
Never write a number for the price yourself. Sign as "Your forwarding team" (in German: "Ihr Forwarding-Team")."""

# USD per 1M tokens (input, output). Only used for our own log; 5U measures the real cost.
PRICES = {"gpt-4o-mini": (0.15, 0.60)}

FALLBACK_REPLY = ("Hello,\n\nthank you for your request. Our all-in price is {PRICE} with {AIRLINE}, "
                  "transit time {TRANSIT_DAYS} days.\n\nBest regards\nYour forwarding team")


def extract(mail):
    """Returns (fields dict, usage dict). Exactly one gateway call."""
    if config.LLM_FAKE:
        return _fake(mail), {"fake": True}
    status, data = mailbox.api("POST", "/v1/gateway/chat/completions", timeout=45, body={
        "model": config.LLM_MODEL,
        "max_completion_tokens": config.LLM_MAX_TOKENS,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": SYSTEM},
                     {"role": "user", "content": "Subject: %s\n\n%s" % (mail["subject"], mail["body"][:6000])}],
    })
    if status != 200:
        raise RuntimeError("gateway %s: %s" % (status, str(data)[:300]))
    fields = json.loads(data["choices"][0]["message"]["content"])
    u = data.get("usage") or {}
    usage = {"model": config.LLM_MODEL, "in": u.get("prompt_tokens"), "out": u.get("completion_tokens")}
    if config.LLM_MODEL in PRICES and usage["in"] is not None:
        pi, po = PRICES[config.LLM_MODEL]
        usage["cost_usd"] = round((usage["in"] * pi + usage["out"] * po) / 1e6, 6)
    return fields, usage


def _fake(mail):
    """No network. Crude regex so everyone can test the loop without a key."""
    text = mail["subject"] + " " + mail["body"]
    codes = re.findall(r"\b[A-Z]{3}\b", text)
    kg = re.search(r"([\d.]+)\s*kg", text, re.I)
    cbm = re.search(r"([\d.]+)\s*(?:cbm|m3)", text, re.I)
    return {"origin": codes[0] if codes else None, "destination": codes[1] if len(codes) > 1 else None,
            "pickup_postcode": None, "weight_kg": float(kg.group(1)) if kg else None,
            "volume_cbm": float(cbm.group(1)) if cbm else None, "pieces": [],
            "prefer": "fastest" if re.search(r"fastest|urgent|schnell", text, re.I) else "cheapest",
            "missing": [], "reply": FALLBACK_REPLY}
