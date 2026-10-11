"""Read Claude Code transcripts and aggregate token usage.

Transcripts are append-only JSONL under ~/.claude/projects/<slug>/<session>.jsonl.
Assistant records carry message.usage; the same record can appear more than once
(one line per streamed iteration), so everything is de-duplicated by message id.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
BLOCK_HOURS = 5

# USD per 1M tokens: (input, output). Cache read is 0.1x input,
# 5m cache write 1.25x input, 1h cache write 2.0x input.
PRICES = {
    "fable": (10.0, 50.0),
    "mythos": (10.0, 50.0),
    "opus": (5.0, 25.0),
    "sonnet": (3.0, 15.0),
    "haiku": (1.0, 5.0),
}
FALLBACK_PRICE = (3.0, 15.0)


def family(model: str) -> str:
    m = (model or "").lower()
    for key in PRICES:
        if key in m:
            return key
    return "other"


def _cost(fam: str, u: dict) -> float:
    pin, pout = PRICES.get(fam, FALLBACK_PRICE)
    cc = u.get("cache_creation") or {}
    w5 = cc.get("ephemeral_5m_input_tokens", 0)
    w1h = cc.get("ephemeral_1h_input_tokens", 0)
    if not (w5 or w1h):  # older records only have the flat counter
        w5 = u.get("cache_creation_input_tokens", 0)
    return (
        u.get("input_tokens", 0) * pin
        + u.get("output_tokens", 0) * pout
        + u.get("cache_read_input_tokens", 0) * pin * 0.10
        + w5 * pin * 1.25
        + w1h * pin * 2.00
    ) / 1_000_000


class Reader:
    """Incrementally tails every transcript file, keeping parsed entries."""

    def __init__(self):
        self.offsets: dict[str, int] = {}
        self.seen: set[str] = set()
        self.entries: list[dict] = []

    def refresh(self) -> None:
        if not PROJECTS.is_dir():
            return
        new = False
        for path in PROJECTS.glob("*/*.jsonl"):
            key = str(path)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            start = self.offsets.get(key, 0)
            if size < start:  # file was rewritten; re-read from the top
                start = 0
            if size == start:
                continue
            try:
                with open(path, "rb") as fh:
                    fh.seek(start)
                    chunk = fh.read()
            except OSError:
                continue
            # only consume whole lines; leave a partial tail for next time
            cut = chunk.rfind(b"\n")
            if cut == -1:
                continue
            self.offsets[key] = start + cut + 1
            for raw in chunk[:cut].split(b"\n"):
                if self._add(raw):
                    new = True
        if new:
            self.entries.sort(key=lambda e: e["ts"])

    def _add(self, raw: bytes) -> bool:
        if b'"usage"' not in raw:
            return False
        try:
            rec = json.loads(raw)
        except ValueError:
            return False
        if rec.get("type") != "assistant":
            return False
        msg = rec.get("message") or {}
        usage = msg.get("usage")
        model = msg.get("model") or ""
        if not usage or not model or model.startswith("<"):
            return False
        mid = msg.get("id") or rec.get("requestId") or rec.get("uuid")
        if not mid or mid in self.seen:
            return False
        self.seen.add(mid)
        try:
            ts = datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            return False
        fam = family(model)
        cc = usage.get("cache_creation") or {}
        tokens = (
            usage.get("input_tokens", 0)
            + usage.get("output_tokens", 0)
            + usage.get("cache_read_input_tokens", 0)
            + max(
                usage.get("cache_creation_input_tokens", 0),
                cc.get("ephemeral_5m_input_tokens", 0)
                + cc.get("ephemeral_1h_input_tokens", 0),
            )
        )
        self.entries.append(
            {
                "ts": ts.timestamp(),
                "family": fam,
                "cost": _cost(fam, usage),
                "tokens": tokens,
            }
        )
        return True


def _blocks(entries: list[dict]) -> list[dict]:
    """Group entries into 5-hour usage windows, anchored to the hour."""
    out: list[dict] = []
    span = BLOCK_HOURS * 3600
    for e in entries:
        cur = out[-1] if out else None
        if cur is None or e["ts"] >= cur["start"] + span or e["ts"] - cur["last"] >= span:
            anchor = datetime.fromtimestamp(e["ts"], timezone.utc).replace(
                minute=0, second=0, microsecond=0
            )
            cur = {"start": anchor.timestamp(), "last": e["ts"], "cost": 0.0,
                   "tokens": 0, "models": {}}
            out.append(cur)
        cur["last"] = e["ts"]
        cur["cost"] += e["cost"]
        cur["tokens"] += e["tokens"]
        m = cur["models"].setdefault(e["family"], {"cost": 0.0, "tokens": 0})
        m["cost"] += e["cost"]
        m["tokens"] += e["tokens"]
    return out


def snapshot(reader: Reader, budget: float, auto_calibrate: bool = True) -> dict:
    """Current-window percentage, reset countdown, model split, and today's shape."""
    reader.refresh()
    now = datetime.now().timestamp()
    blocks = _blocks(reader.entries)

    high_water = max((b["cost"] for b in blocks), default=0.0)
    if auto_calibrate and high_water > budget:
        budget = high_water

    span = BLOCK_HOURS * 3600
    cur = blocks[-1] if blocks else None
    if cur is None or now >= cur["start"] + span:
        cur = {"start": None, "cost": 0.0, "tokens": 0, "models": {}}
        remaining = 0.0
    else:
        remaining = cur["start"] + span - now

    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    hourly = [0.0] * 24
    today_cost = 0.0
    today_tokens = 0
    today_models: dict[str, dict] = {}
    for e in reader.entries:
        if e["ts"] < midnight:
            continue
        hour = int((e["ts"] - midnight) // 3600)
        if 0 <= hour < 24:
            hourly[hour] += e["cost"]
        today_cost += e["cost"]
        today_tokens += e["tokens"]
        m = today_models.setdefault(e["family"], {"cost": 0.0, "tokens": 0})
        m["cost"] += e["cost"]
        m["tokens"] += e["tokens"]

    return {
        "pct": min(cur["cost"] / budget, 1.0) if budget > 0 else 0.0,
        "budget": budget,
        "block_cost": cur["cost"],
        "block_tokens": cur["tokens"],
        "block_models": cur["models"],
        "block_start": cur["start"],
        "remaining": remaining,
        "today_cost": today_cost,
        "today_tokens": today_tokens,
        "today_models": today_models,
        "hourly": hourly,
        "hour_now": int((now - midnight) // 3600),
        "high_water": high_water,
    }
