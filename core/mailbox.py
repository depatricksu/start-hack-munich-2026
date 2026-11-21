"""5U mailbox API: poll and send. The only place that talks to the mailbox."""
import datetime, json, time, urllib.error, urllib.parse, urllib.request
from . import config, db


def api(method, path, body=None, params=None, timeout=20):
    """One HTTP call to the 5U API. Returns (status, json or text)."""
    url = config.BASE_URL + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-API-Key": config.API_KEY, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw, status, headers = r.read().decode(), r.status, r.headers
    except urllib.error.HTTPError as e:
        raw, status, headers = e.read().decode(), e.code, e.headers
    try:
        data = json.loads(raw)
    except ValueError:
        data = raw
    if status == 429:
        data = {"retry_after": float(headers.get("Retry-After", 5)), "detail": data}
    return status, data


def _first(d, *keys):
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return None


def _ts(v):
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


def normalize(raw):
    """Turn a 5U mail into our own small dict. The spec does not fix the field names, so we accept a few."""
    refs = raw.get("references") or []
    parent = _first(raw, "in_reply_to", "parent_id")
    mid = raw["id"]
    sender = _first(raw, "from", "sender", "from_address", "from_email") or ""
    if isinstance(sender, dict):
        sender = _first(sender, "email", "address") or ""
    return {
        "id": mid, "sender": sender.strip().lower(), "subject": raw.get("subject") or "", "body": raw.get("body") or "",
        "thread_id": refs[0] if refs else (parent or mid),      # id of the first mail in the thread
        "is_thread_start": not refs and not parent,
        "attachments": raw.get("attachments") or [],
        "received_at": _ts(_first(raw, "created_at", "sent_at", "received_at", "timestamp", "date") or time.time()),
        "raw": raw,
    }


class RateLimited(Exception):
    def __init__(self, retry_after):
        super().__init__("poll rate limited, retry after %.1f s" % retry_after)
        self.retry_after = retry_after


def poll(since_id):
    """New mails after since_id, oldest first. Returns (mails, next_since_id)."""
    status, data = api("GET", "/v1/mailbox/messages", params={"since_id": since_id, "limit": 200})
    if status == 429:                                # 5U: one poll per 5 s per key; wait what they ask
        raise RateLimited(float((data or {}).get("retry_after", 5)) if isinstance(data, dict) else 5.0)
    if status != 200:
        raise RuntimeError("poll failed %s: %s" % (status, str(data)[:200]))
    items = data.get("messages") or data.get("items") or data.get("data") or [] if isinstance(data, dict) else data
    mails = [normalize(m) for m in items]
    nxt = data.get("next_since_id") if isinstance(data, dict) else None
    return mails, nxt if nxt is not None else max([m["id"] for m in mails] + [since_id])


def in_customer_language(to, body, thread_id, event="mail_out"):
    """5U 23:00 (21 Nov): a reply that is not in the customer's language is rejected (wrong_language). For a customer
    whose language we have no own texts for, every mail to them is translated here, as a whole, right before it goes
    out (llm/translate.py). Mails to carriers and customers we can write to ourselves pass through unchanged. Any
    problem -> the English mail goes out as before, and the event log says why."""
    if event != "mail_out" or not thread_id:
        return body
    try:
        s = db.session(thread_id)
        if not s or (s.get("customer") or "").lower() != (to or "").lower():
            return body
        lang = (json.loads(s.get("fields") or "{}").get("language") or "").lower()[:2]
        from llm import translate                             # late import: llm imports this module
        if not translate.needed(lang):
            return body
        text, info = translate.to(body, lang)
        if not text:
            db.event("translate_failed", thread_id, lang=lang, why=info)
            return body
        db.event("translated", thread_id, lang=lang, cost_usd=info, english=body)
        if info:
            db.update_session(thread_id, llm_cost_usd=(s.get("llm_cost_usd") or 0) + info)
        return text
    except Exception as e:
        db.event("translate_failed", thread_id, why="error: %s" % str(e)[:200])
        return body


def send(to, subject, body, in_reply_to=None, thread_id=None, event="mail_out"):
    """Send a mail. With DRY_RUN=1 it is only logged. Returns True if sent (or dry run).

    event: name of the log entry. Customer mails are "mail_out"; bid requests to carriers use "bid_mail_out",
    so "mails we sent the customer" stays easy to count."""
    body = in_customer_language(to, body, thread_id, event)
    if config.DRY_RUN:
        db.event(event + "_dry_run", thread_id, in_reply_to, to=to, subject=subject, body=body)
        return True
    payload = {"to": to, "subject": subject, "body": body}
    if in_reply_to:
        payload["in_reply_to"] = in_reply_to
    for _ in range(3):
        status, data = api("POST", "/v1/mailbox/messages", body=payload)
        if status == 429:
            time.sleep(min(data["retry_after"], 10))
            continue
        break
    ok = status in (200, 201)
    db.event(event if ok else event + "_failed", thread_id, in_reply_to, to=to, subject=subject, body=body,
             status=status, response=data)
    return ok
