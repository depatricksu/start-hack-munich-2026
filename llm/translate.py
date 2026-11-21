"""A mail to a customer whose language we have no own texts for (Chinese, Dutch, Polish...) is written in English by
the normal path, with every gate, and translated as a whole right before it is sent (core/mailbox.send).

5U, 21 Nov 23:12, round 72: the customer wrote in Chinese, we answered in English, the customer answered "It wasn't in
the language I wrote to you in, and I couldn't follow it, so we won't go ahead" and the round was rejected
(wrong_language). One more gateway call per mail, only for these languages.
"""
import re
from core import config, mailbox
from . import lang as langmod

SYSTEM = """You translate an email from a freight forwarder to a customer into %s.
Translate everything, also the greeting, the question at the end and the closing line.
Keep exactly as written: every number and amount, "EUR", names of airlines and companies, names of people, airport
codes, booking numbers and offer numbers. Do not reformat numbers: 2353.76 stays 2353.76, with the decimal point.
Never transliterate a name: "Polaris Air Logistics" and "Lena Hofmann" stay in Latin letters.
Keep the paragraphs and line breaks. Do not add or drop a sentence.
Write as a native business correspondent would. Return only the translated email, nothing else."""
AMOUNT = re.compile(r"\d+\.\d{2}\b")            # 2353.76: every amount of the English mail must be in the translation


def restore_amounts(text, english):
    """The price must reach the customer (and 5U's scorer) exactly as we quoted it. Many languages write 2.353,76 or
    2 353,76: put our own form back wherever the same digits appear with other separators."""
    for a in set(AMOUNT.findall(english)):
        if a in text:
            continue
        whole, cents = a.split(".")
        groups = []
        while len(whole) > 3:
            whole, last = whole[:-3], whole[-3:]
            groups.insert(0, last)
        pattern = re.escape(whole) + "".join(r"[.,'\s\u00a0\u202f]?" + g for g in groups) + "[.,]" + cents + r"(?!\d)"
        text = re.sub(r"(?<!\d)" + pattern, a, text)
    return text


def needed(lang):
    lang = (lang or "").lower()[:2]
    return bool(lang) and lang not in langmod.OWN


def to(body, lang):
    """-> (translated body, cost in USD) or (None, reason). Never raises."""
    if config.LLM_FAKE or not (body or "").strip():
        return None, "no gateway (LLM_FAKE)"
    try:
        status, data = mailbox.api("POST", "/v1/gateway/chat/completions", timeout=25, body={
            "model": config.LLM_MODEL, "max_completion_tokens": 1200,
            "messages": [{"role": "system", "content": SYSTEM % langmod.name(lang)}, {"role": "user", "content": body}]})
        if status != 200:
            return None, "gateway %s: %s" % (status, str(data)[:160])
        text = restore_amounts((data["choices"][0]["message"]["content"] or "").strip(), body)
        missing = [a for a in set(AMOUNT.findall(body)) if a not in text]
        if len(text) < 20 or missing:
            return None, "translation dropped %s" % (missing or "the text")
        u = data.get("usage") or {}
        return text, round(((u.get("prompt_tokens") or 0) * 0.15 + (u.get("completion_tokens") or 0) * 0.60) / 1e6, 6)
    except Exception as e:
        return None, "error: %s" % str(e)[:160]
