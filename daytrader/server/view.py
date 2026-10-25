"""The view the Dynamic Island and the Android app show.

Both clients are deliberately "dumb": they render this structure and send
back answers. Every word, number and layout decision is made here, so
changing this file changes what the island and the phone show, with no
release of either. The format is documented in docs/island-protocol.md.
"""

from __future__ import annotations

import time

PROTOCOL = 1

EXIT_WORDS = {
    "stop": "stop hit",
    "target": "target hit",
    "square_off": "squared off",
    "daily_loss_limit": "daily loss limit",
    "kill_switch": "kill switch",
    "end_of_day": "end of day",
    "no_broker_stop": "no broker stop",
}


def inr(x: float, sign: bool = False) -> str:
    """Indian digit grouping: 1234567.8 -> Rs 12,34,567.80 (with the rupee sign)."""
    neg = x < 0
    whole, frac = f"{abs(x):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    s = f"₹{whole}.{frac}"
    if neg:
        return "−" + s
    return ("+" + s) if sign and x > 0 else s


def short_inr(x: float) -> str:
    """Fits the narrow capsule: +₹640, −₹1.2k, +₹3.4L, +₹1.1Cr."""
    a = abs(x)
    if a >= 1e7:
        body = f"{a / 1e7:.1f}Cr"
    elif a >= 1e5:
        body = f"{a / 1e5:.1f}L"
    elif a >= 1e3:
        body = f"{a / 1e3:.1f}k"
    else:
        body = f"{a:.0f}"
    sign = "−" if x < 0 else "+" if x > 0 else ""
    return f"{sign}₹{body}"


def tone(x: float) -> str:
    return "up" if x > 0 else "down" if x < 0 else "neutral"


def manifest(phone_url: str | None = None, token: str | None = None) -> dict:
    m = {
        "protocol": PROTOCOL,
        "id": "trading",
        "name": "Trading",
        "color": "#22c55e",
        "description": "Your Day-Trading engine: today's P&L on the island, approve or skip each trade, "
                       "and stop trading for the day.",
        "permissions": ["Reads your trading engine's positions and P&L",
                        "Sends your Approve or Skip answers back to it"],
        "tab_title": "Trading",
    }
    if phone_url and token:
        from urllib.parse import quote
        m["phone_url"] = phone_url
        m["pairing_link"] = f"daytrader://pair?url={quote(phone_url, safe='')}&token={quote(token, safe='')}"
    return m


def _ask(p: dict) -> dict:
    side_word = "Buy" if p["side"] == "BUY" else "Sell short"
    lines = [
        {"label": "Price", "value": f"~{inr(p['ref_price'])}"},
        {"label": "Value", "value": inr(p["value"])},
        {"label": "Stop", "value": inr(p["stop"])},
    ]
    if p.get("target"):
        lines.append({"label": "Target", "value": inr(p["target"])})
    lines.append({"label": "Risk", "value": inr(p["risk_rupees"]), "tone": "down"})
    return {
        "id": p["id"],
        "title": f"{side_word} {p['qty']} {p['symbol']}",
        "subtitle": f"{p['symbol']} · {p['market_time'][11:16]}",
        "lines": lines,
        "note": p.get("reason", ""),
        "approve_label": "Buy" if p["side"] == "BUY" else "Sell",
        "reject_label": "Skip",
        "seconds_left": p["seconds_left"],
        "expires_at": int(p["expires_at"] * 1000),
        "tone": "up" if p["side"] == "BUY" else "down",
    }


def build_view(state: dict, now: float | None = None) -> dict:
    now = now if now is not None else time.time()
    net = state["net_today"]
    mode = state["mode"].upper()
    pending = [p for p in state["proposals"] if p["status"] == "pending"]

    detail_bits = [f"{state['open_positions']} open", f"{state['trades_today']} trades"]
    if state["killed"]:
        detail_bits.insert(0, "stopped")
    detail_bits.append(mode)
    status = {
        "text": inr(net, sign=True),
        "short": short_inr(net),
        "tone": "warn" if state["killed"] else tone(net),
        "detail": " · ".join(detail_bits),
        # Only take space on the island when there is something to watch.
        "show": bool(state["open_positions"] or state["trades_today"] or pending or state["killed"]),
    }

    used = state["loss_limit_used_pct"]
    stats = {
        "type": "stats",
        "items": [
            {"label": "Today", "value": inr(net, sign=True), "tone": tone(net)},
            {"label": "Realized", "value": inr(state["realized_today"], sign=True), "tone": tone(state["realized_today"])},
            {"label": "Open P&L", "value": inr(state["unrealized"], sign=True), "tone": tone(state["unrealized"])},
            {"label": "Charges", "value": inr(state["charges_today"])},
            {"label": "Loss limit used", "value": f"{used:g}% of {inr(state['daily_loss_limit'])}",
             "tone": "down" if used >= 75 else "neutral"},
            {"label": "Mode", "value": mode + (" · " + state["feed"] if state.get("feed") else ""),
             "tone": "warn" if mode == "LIVE" else "neutral"},
        ],
    }
    sections: list[dict] = []
    if state["killed"]:
        sections.append({"type": "note", "tone": "warn",
                         "text": f"Trading is stopped for today: {state['kill_reason']}. It starts again tomorrow."})
    sections.append(stats)
    sections.append({
        "type": "list", "title": "Open positions", "empty": "No open positions",
        "rows": [{
            "title": f"{'Long' if x['side'] == 'BUY' else 'Short'} {x['qty']} {x['symbol']}",
            "subtitle": f"in {inr(x['entry_price'])} · now {inr(x['ltp'])} · stop {inr(x['stop'])}"
                        + (" · stop at broker" if x.get("broker_stop") else ""),
            "value": inr(x["unrealized"], sign=True), "tone": tone(x["unrealized"]),
        } for x in state["positions"]],
    })
    sections.append({
        "type": "list", "title": "Today's trades", "empty": "No trades yet today",
        "rows": [{
            "title": f"{t['symbol']} {'long' if t['side'] == 'BUY' else 'short'} {t['qty']}",
            "subtitle": f"{t['entry_time'][11:16]} to {t['exit_time'][11:16]} · "
                        f"{EXIT_WORDS.get(t['exit_reason'], t['exit_reason'])} · charges {inr(t['charges'])}",
            "value": inr(t["net_pnl"], sign=True), "tone": tone(t["net_pnl"]),
        } for t in state["trades"][:20]],
    })
    decided = [p for p in state["proposals"] if p["status"] != "pending"][:8]
    if decided:
        words = {"placed": "placed", "rejected": "skipped", "expired": "no answer", "stale": "price moved",
                 "failed": "broker refused"}
        sections.append({
            "type": "list", "title": "Recent approvals",
            "rows": [{
                "title": f"{p['side'].title()} {p['qty']} {p['symbol']}",
                "subtitle": (p.get("note") or "") + (f" · {p['decided_by']}" if p.get("decided_by") else ""),
                "value": words.get(p["status"], p["status"]),
                "tone": "up" if p["status"] == "placed" else "neutral",
            } for p in decided],
        })
    actions = []
    if not state["killed"]:
        actions.append({"id": "stop_today", "label": "Stop trading today", "style": "danger",
                        "confirm": "No new trades today. Open positions keep their stops."})
    if state["open_positions"]:
        actions.append({"id": "flatten", "label": "Close everything now", "style": "danger",
                        "confirm": "Close every open position at market and stop for today?"})
    if actions:
        sections.append({"type": "actions", "actions": actions})
    sections.append({"type": "note", "tone": "neutral",
                     "text": f"Strategy {state['strategy']['name'].upper()} · capital {inr(state['capital'])}"
                             f" · {state.get('market_time') or 'waiting for market data'}"})
    return {
        "protocol": PROTOCOL,
        "updated_at": int(now * 1000),
        "status": status,
        "asks": [_ask(p) for p in pending],
        "sections": sections,
    }


def notification_for(ev: dict) -> dict | None:
    """A short heads-up for events worth interrupting you for."""
    t, d = ev["type"], ev["data"]
    if t == "position_opened":
        verb = "Bought" if d["side"] == "BUY" else "Sold short"
        return {"title": f"{verb} {d['qty']} {d['symbol']} @ {inr(d['entry_price'])}",
                "body": f"Stop {inr(d['stop'])}" + (f" · target {inr(d['target'])}" if d.get("target") else ""),
                "urgency": "normal"}
    if t == "position_closed":
        return {"title": f"{d['symbol']} closed: {inr(d['net_pnl'], sign=True)}",
                "body": f"{EXIT_WORDS.get(d['exit_reason'], d['exit_reason'])} · charges {inr(d['charges'])}",
                "urgency": "normal"}
    if t == "alert":
        return {"title": "Trading alert", "body": d["message"], "urgency": "critical"}
    if t == "killed":
        return {"title": "Trading stopped for today", "body": d["reason"], "urgency": "normal"}
    if t == "proposal_update" and d["status"] in ("stale", "failed"):
        return {"title": f"Not placed: {d['side'].title()} {d['qty']} {d['symbol']}", "body": d.get("note", ""),
                "urgency": "normal"}
    return None
