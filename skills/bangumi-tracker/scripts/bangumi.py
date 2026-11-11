#!/usr/bin/env python3
"""Bangumi airing tracker: what airs today, next episodes, and a personal watchlist.

Standard library only. Public Bangumi API (https://api.bgm.tv, no key). Output is JSON.

  bangumi.py today [--all]          watchlist titles airing today (Japan date); --all = every title
  bangumi.py search <keyword>       find anime (id, names, first air date)
  bangumi.py next <subject_id>      next episode number and air date
  bangumi.py watch list|add <id>|remove <id>

Watchlist and cache live in $HERMES_HOME/bangumi/ (default ~/.hermes/bangumi/).
Titles from the API are untrusted text: they are cleaned (control/invisible characters
removed, length capped) and returned as data. Summaries are never returned.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

API = "https://api.bgm.tv"
JST = ZoneInfo("Asia/Tokyo")
# Bangumi asks clients to identify themselves; no personal contact info is sent.
USER_AGENT = os.environ.get("BANGUMI_USER_AGENT",
                            "hermes-bangumi-tracker/1.0 (+https://github.com/ZQC8848/hermes-skill-bangumi)")
HOME = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes")
DATA = HOME / "bangumi"
WATCHLIST = DATA / "watchlist.json"
CALENDAR_CACHE = DATA / "calendar_cache.json"
CACHE_TTL_S = 6 * 3600
MAX_WATCH = 50
_CTRL = re.compile("[\x00-\x1f\x7f​-‏‪-‮⁠-⁤﻿]")


def clean(text: object, limit: int = 80) -> str:
    s = _CTRL.sub("", str(text or "")).strip()
    return s if len(s) <= limit else s[: limit - 1] + "…"


def request(path: str, *, method: str = "GET", body: dict | None = None) -> object:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={
        "User-Agent": USER_AGENT, "Accept": "application/json",
        **({"Content-Type": "application/json"} if data else {})})
    last: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.load(r)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise LookupError("not found") from exc
            last = exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
        time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Bangumi API unavailable ({type(last).__name__})")


def calendar() -> list[dict]:
    try:
        cached = json.loads(CALENDAR_CACHE.read_text())
        if time.time() - cached["at"] < CACHE_TTL_S:
            return cached["days"]
    except (FileNotFoundError, KeyError, ValueError):
        pass
    days = request("/calendar")
    DATA.mkdir(parents=True, exist_ok=True)
    CALENDAR_CACHE.write_text(json.dumps({"at": time.time(), "days": days}))
    return days


def item_view(it: dict) -> dict:
    return {"id": it["id"], "name": clean(it.get("name")), "name_cn": clean(it.get("name_cn")),
            "air_weekday_jst": it.get("air_weekday"), "url": f"https://bgm.tv/subject/{it['id']}"}


def load_watchlist() -> list[dict]:
    try:
        return json.loads(WATCHLIST.read_text())
    except (FileNotFoundError, ValueError):
        return []


def save_watchlist(items: list[dict]) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = WATCHLIST.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1))
    os.replace(tmp, WATCHLIST)  # atomic: a crash never leaves half a watchlist


def next_episode(subject_id: int) -> dict:
    today = dt.datetime.now(JST).date().isoformat()
    first = request(f"/v0/episodes?subject_id={subject_id}&type=0&limit=1")
    total = int(first.get("total", 0))
    if not total:
        return {"id": subject_id, "next": None, "detail": "no episode list"}
    page = request(f"/v0/episodes?subject_id={subject_id}&type=0&limit=100&offset={max(0, total - 100)}")
    eps = [e for e in page.get("data", []) if e.get("airdate")]
    upcoming = [e for e in eps if e["airdate"] >= today]
    aired = [e for e in eps if e["airdate"] < today]
    out: dict = {"id": subject_id}
    if upcoming:
        e = upcoming[0]
        out["next"] = {"episode": e.get("ep") or e.get("sort"), "airdate_jst": e["airdate"],
                       "title": clean(e.get("name_cn") or e.get("name"))}
    else:
        out["next"] = None
    if aired:
        out["latest_aired"] = {"episode": aired[-1].get("ep") or aired[-1].get("sort"),
                               "airdate_jst": aired[-1]["airdate"]}
    return out


def cmd_today(show_all: bool) -> dict:
    weekday = dt.datetime.now(JST).isoweekday()  # Bangumi: 1 = Monday … 7 = Sunday
    day = next((d for d in calendar() if d.get("weekday", {}).get("id") == weekday), {"items": []})
    items = [item_view(it) for it in day.get("items", [])]
    watched = {w["id"] for w in load_watchlist()}
    now = dt.datetime.now(JST)
    date_jst = f"{now:%Y-%m-%d} ({now:%A})"  # weekday spelled out: models miscount it otherwise
    if show_all:
        return {"date_jst": date_jst, "count": len(items), "airing": items[:40]}
    mine = [it for it in items if it["id"] in watched]
    for it in mine:
        try:
            it.update({k: v for k, v in next_episode(it["id"]).items() if k != "id"})
        except Exception as exc:  # one failing title must not hide the others
            it["next_error"] = type(exc).__name__
    return {"date_jst": date_jst, "watchlist_size": len(watched), "airing_today": mine}


def cmd_search(keyword: str) -> dict:
    res = request("/v0/search/subjects?limit=5", method="POST",
                  body={"keyword": keyword[:60], "filter": {"type": [2]}})
    return {"results": [{"id": s["id"], "name": clean(s.get("name")), "name_cn": clean(s.get("name_cn")),
                         "first_aired": s.get("date")} for s in res.get("data", [])]}


def cmd_watch(action: str, arg: str | None) -> dict:
    items = load_watchlist()
    if action == "list":
        return {"watchlist": items}
    if not arg or not arg.isdigit():
        raise ValueError("watch add/remove needs a numeric subject id (use search first)")
    sid = int(arg)
    if action == "add":
        if any(w["id"] == sid for w in items):
            return {"added": False, "detail": "already on the watchlist", "watchlist_size": len(items)}
        if len(items) >= MAX_WATCH:
            raise ValueError(f"watchlist is full ({MAX_WATCH})")
        s = request(f"/v0/subjects/{sid}")
        if s.get("type") != 2:
            raise ValueError("subject is not an anime")
        items.append({"id": sid, "name": clean(s.get("name")), "name_cn": clean(s.get("name_cn"))})
        save_watchlist(items)
        return {"added": True, "item": items[-1], "watchlist_size": len(items)}
    if action == "remove":
        kept = [w for w in items if w["id"] != sid]
        save_watchlist(kept)
        return {"removed": len(kept) != len(items), "watchlist_size": len(kept)}
    raise ValueError("watch action must be list, add or remove")


def main(argv: list[str]) -> int:
    try:
        if not argv:
            raise ValueError("usage: bangumi.py today [--all] | search <kw> | next <id> | watch list|add|remove [id]")
        cmd = argv[0]
        if cmd == "today":
            out = cmd_today("--all" in argv[1:])
        elif cmd == "search" and len(argv) > 1:
            out = cmd_search(" ".join(argv[1:]))
        elif cmd == "next" and len(argv) > 1 and argv[1].isdigit():
            out = next_episode(int(argv[1]))
        elif cmd == "watch" and len(argv) > 1:
            out = cmd_watch(argv[1], argv[2] if len(argv) > 2 else None)
        else:
            raise ValueError(f"unknown command: {' '.join(argv)[:60]}")
    except (ValueError, LookupError, RuntimeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
