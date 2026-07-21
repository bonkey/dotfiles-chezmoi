#!/usr/bin/env python3
"""Batch-apply simslim service profiles to iOS simulators.

Profiles:
  all      turn off every simslim category
  extras   turn off everything except App Store, PIM, other, web, photos, connectivity
  none     restore stock (all services back on)

Subtract categories from a profile with -<category> (keeps that category on):
  simslim-profile.py all -family
  simslim-profile.py extras -siri -appstore

With no arguments (on a terminal) an interactive curses picker opens.
See `simslim profiles` for the category list.
"""

import argparse
import curses
import fnmatch
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

SIMSLIM = "simslim"

# Used only when the installed simslim can't report its categories.
FALLBACK_CATEGORIES = [
    ("widgets", "Widgets & Wallpaper"),
    ("siri", "Siri & Intelligence"),
    ("search", "Spotlight & Search"),
    ("icloud", "iCloud & Apple Account"),
    ("store", "App Store, Push & Media"),
    ("pim", "Mail, Calendar & Contacts"),
    ("web", "Safari Sync & Web Services"),
    ("family", "Family & Screen Time"),
    ("health", "Health, Home & Fitness"),
    ("photos", "Photos & Media Analysis"),
    ("apps", "News, Weather, Maps & Games"),
    ("messaging", "Messaging & FaceTime"),
    ("connectivity", "Sharing & Device Connectivity"),
    ("telemetry", "Ads, Diagnostics & Telemetry"),
    ("other", "Other Background Services"),
]
EXTRAS_KEEP = {"store", "pim", "other", "web", "photos", "connectivity"}
ALIASES = {"appstore": "store", "app-store": "store"}


@dataclass
class Device:
    udid: str
    name: str
    state: str
    os: str


def die(msg):
    print(f"simslim-profile: {msg}", file=sys.stderr)
    sys.exit(2)


def get_categories():
    out = subprocess.run([SIMSLIM, "profiles", "--json"], capture_output=True, text=True)
    if out.returncode == 0:
        try:
            return [(c["id"], c["name"]) for c in json.loads(out.stdout)]
        except (json.JSONDecodeError, KeyError, TypeError):
            pass
    out = subprocess.run([SIMSLIM, "profiles"], capture_output=True, text=True)
    if out.returncode == 0:
        cats = re.findall(r"^([a-z][a-z0-9-]*) {2,}(\S.*)$", out.stdout, re.M)
        if cats:
            return cats
    return FALLBACK_CATEGORIES


def get_devices():
    out = subprocess.run(
        ["xcrun", "simctl", "list", "devices", "available", "--json"],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        die(f"simctl list failed: {out.stderr.strip()}")
    devices = []
    for runtime, devs in json.loads(out.stdout)["devices"].items():
        m = re.search(r"SimRuntime\.iOS-(\d+)-(\d+)", runtime)
        if not m:
            continue
        os_version = f"{m.group(1)}.{m.group(2)}"
        for d in devs:
            devices.append(Device(d["udid"], d["name"], d["state"], os_version))
    devices.sort(key=lambda d: (tuple(-int(p) for p in d.os.split(".")), d.name))
    return devices


def extract_minus(argv, cat_ids):
    """Pull -<category> subtraction tokens out of argv before argparse sees them."""
    rest, minus = [], []
    for a in argv:
        if a.startswith("-") and not a.startswith("--"):
            name = ALIASES.get(a[1:], a[1:])
            if name in cat_ids:
                minus.append(name)
                continue
        rest.append(a)
    return rest, minus


def resolve_profile(base, minus, cat_ids):
    """Return (mode, keep) where mode is 'slim' or 'stock' and keep is the
    set of category IDs left enabled."""
    base = ALIASES.get(base, base)
    if base == "all":
        mode, keep = "slim", set()
    elif base == "extras":
        mode, keep = "slim", EXTRAS_KEEP & cat_ids
    elif base in ("none", "stock"):
        mode, keep = "stock", set()
    else:
        die(f'unknown profile "{base}" (all, extras, none)')
    if minus:
        if mode == "stock":
            die("cannot subtract categories from 'none'")
        keep |= set(minus)
    return mode, keep


def profile_label(mode, keep):
    if mode == "stock":
        return "stock (nothing off)"
    if not keep:
        return "all"
    if keep == EXTRAS_KEEP:
        return "extras"
    return "all " + " ".join(f"-{c}" for c in sorted(keep))


def select_devices(devices, patterns, booted):
    if booted:
        devices = [d for d in devices if d.state == "Booted"]
    if not patterns:
        return devices
    sel, seen = [], set()
    for pat in patterns:
        low = pat.lower()
        matched = [
            d for d in devices
            if d.udid.lower() == low or d.name.lower() == low
            or fnmatch.fnmatch(d.name.lower(), low)
        ]
        if not matched:
            die(f'no simulator matches "{pat}"')
        for d in matched:
            if d.udid not in seen:
                seen.add(d.udid)
                sel.append(d)
    return sel


def preserve_supported():
    out = subprocess.run([SIMSLIM], capture_output=True, text=True)
    return "preserve-boot-state" in (out.stdout + out.stderr)


def apply_profile(devices, mode, keep, args, preserve):
    failures = 0
    total = len(devices)
    for i, d in enumerate(devices, 1):
        # Flags must precede the UDID: simslim 0.1.0 stops flag parsing at the
        # first positional argument.
        cmd = [SIMSLIM, "off" if mode == "stock" else "on"]
        if mode == "slim" and keep:
            cmd += ["--except", ",".join(sorted(keep))]
        if preserve:
            cmd += ["--preserve-boot-state"]
        cmd.append(d.udid)
        if args.dry_run:
            print(" ".join(cmd))
            continue
        label = f"[{i}/{total}] {d.name} (iOS {d.os})"
        if args.verbose:
            print(f"— {label}")
            rc = subprocess.run(cmd).returncode
        else:
            verb = "restoring" if mode == "stock" else "slimming"
            print(f"{label}: {verb}… ", end="", flush=True)
            out = subprocess.run(cmd, capture_output=True, text=True)
            rc = out.returncode
            if rc == 0:
                tail = (out.stdout.strip().splitlines() or ["done"])[-1]
                print(tail)
            else:
                err = (out.stderr.strip().splitlines() or ["failed"])[-1]
                print(f"FAILED — {err}")
        # Older simslim leaves an originally-shutdown simulator booted.
        if rc == 0 and not preserve and d.state == "Shutdown":
            subprocess.run(["xcrun", "simctl", "shutdown", d.udid], capture_output=True)
        failures += rc != 0
    return failures


# --- TUI ---------------------------------------------------------------

def _put(scr, y, x, text, attr=0):
    h, w = scr.getmaxyx()
    if 0 <= y < h and x < w:
        try:
            scr.addnstr(y, x, text, w - x - 1, attr)
        except curses.error:
            pass


ENTER_KEYS = (curses.KEY_ENTER, 10, 13)


def _pick_devices(scr, devices, selected):
    cur = off = 0
    while True:
        scr.erase()
        h, _ = scr.getmaxyx()
        _put(scr, 0, 0, "simslim-profile — simulators", curses.A_BOLD)
        _put(scr, 1, 0, "space toggle · a all · n none · b booted only · enter next · q quit",
             curses.A_DIM)
        rows = h - 3
        if cur < off:
            off = cur
        if cur >= off + rows:
            off = cur - rows + 1
        for i, d in enumerate(devices[off:off + rows]):
            idx = off + i
            mark = "x" if d.udid in selected else " "
            line = f"[{mark}] {d.name:<28.28} iOS {d.os:<6} {d.state}"
            _put(scr, 3 + i, 0, ("> " if idx == cur else "  ") + line,
                 curses.A_REVERSE if idx == cur else 0)
        scr.refresh()
        k = scr.getch()
        if k in (ord("q"), 27):
            return None
        if k in (curses.KEY_UP, ord("k")):
            cur = max(0, cur - 1)
        elif k in (curses.KEY_DOWN, ord("j")):
            cur = min(len(devices) - 1, cur + 1)
        elif k == ord(" "):
            d = devices[cur]
            selected.symmetric_difference_update({d.udid})
        elif k == ord("a"):
            selected.clear()
            selected.update(d.udid for d in devices)
        elif k == ord("n"):
            selected.clear()
        elif k == ord("b"):
            selected.clear()
            selected.update(d.udid for d in devices if d.state == "Booted")
        elif k in ENTER_KEYS and selected:
            return selected


def _pick_profile(scr, cats):
    ids = {c[0] for c in cats}
    on = set()  # categories that stay enabled; empty = profile "all"
    cur = off = 0
    on_attr = curses.A_BOLD
    if curses.has_colors():
        on_attr |= curses.color_pair(1)
    while True:
        stock = on == ids
        mode = "stock" if stock else "slim"
        keep = set() if stock else set(on)
        scr.erase()
        h, _ = scr.getmaxyx()
        _put(scr, 0, 0,
             f"profile: {profile_label(mode, keep)} — {len(ids) - len(on)} off / {len(on)} on",
             curses.A_BOLD)
        _put(scr, 1, 0, "a all off · e extras · s stock (everything on) · space toggle · enter apply · q back",
             curses.A_DIM)
        _put(scr, 2, 0, "ON = service keeps running; everything else is turned off", curses.A_DIM)
        rows = h - 4
        if cur < off:
            off = cur
        if cur >= off + rows:
            off = cur - rows + 1
        for i, (cid, cname) in enumerate(cats[off:off + rows]):
            idx = off + i
            y = 4 + i
            sel = curses.A_REVERSE if idx == cur else 0
            _put(scr, y, 0, "> " if idx == cur else "  ", sel)
            if cid in on:
                _put(scr, y, 2, "ON ", on_attr | sel)
            else:
                _put(scr, y, 2, "off", curses.A_DIM | sel)
            _put(scr, y, 6, f"{cid:<14} {cname}", sel)
        scr.refresh()
        k = scr.getch()
        if k in (ord("q"), 27):
            return None
        if k in (curses.KEY_UP, ord("k")):
            cur = max(0, cur - 1)
        elif k in (curses.KEY_DOWN, ord("j")):
            cur = min(len(cats) - 1, cur + 1)
        elif k == ord("a"):
            on.clear()
        elif k == ord("e"):
            on = EXTRAS_KEEP & ids
        elif k in (ord("n"), ord("s")):
            on = set(ids)
        elif k == ord(" "):
            on.symmetric_difference_update({cats[cur][0]})
        elif k in ENTER_KEYS:
            return mode, keep


def tui(devices, cats):
    result = {}

    def main(scr):
        curses.curs_set(0)
        scr.keypad(True)
        try:
            curses.start_color()
            curses.use_default_colors()
            curses.init_pair(1, curses.COLOR_GREEN, -1)
        except curses.error:
            pass
        selected = {d.udid for d in devices}
        while True:
            if _pick_devices(scr, devices, selected) is None:
                return
            picked = _pick_profile(scr, cats)
            if picked is None:
                continue
            result["devices"] = [d for d in devices if d.udid in selected]
            result["mode"], result["keep"] = picked
            return

    try:
        curses.wrapper(main)
    except curses.error:
        die("TUI needs an interactive terminal")
    return result or None


# --- main --------------------------------------------------------------

def main():
    if not shutil.which(SIMSLIM):
        die("simslim not found (brew install mobai-app/tap/simslim)")
    cats = get_categories()
    cat_ids = {c[0] for c in cats}
    argv, minus = extract_minus(sys.argv[1:], cat_ids)

    ap = argparse.ArgumentParser(
        prog="simslim-profile.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("profile", nargs="?", help="all | extras | none")
    ap.add_argument("-d", "--device", action="append", default=[], metavar="NAME_OR_UDID",
                    help="apply only to matching simulators (name, glob, or UDID; repeatable)")
    ap.add_argument("--booted", action="store_true", help="only booted simulators")
    ap.add_argument("-t", "--tui", action="store_true", help="interactive selection")
    ap.add_argument("--dry-run", action="store_true", help="print simslim commands, don't run")
    ap.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    ap.add_argument("-v", "--verbose", action="store_true", help="stream simslim output")
    args = ap.parse_args(argv)

    devices = get_devices()
    if not devices:
        die("no available iOS simulators")

    use_tui = args.tui or (args.profile is None and sys.stdin.isatty() and sys.stdout.isatty())
    if use_tui and args.profile is not None:
        die("--tui takes no profile argument")

    if use_tui:
        pool = select_devices(devices, args.device, args.booted)
        if not pool:
            die("no simulators match the filters")
        picked = tui(pool, cats)
        if not picked:
            return 0
        targets, mode, keep = picked["devices"], picked["mode"], picked["keep"]
        confirmed = True
    else:
        if args.profile is None:
            ap.error("profile required (all | extras | none) or use --tui")
        mode, keep = resolve_profile(args.profile, minus, cat_ids)
        targets = select_devices(devices, args.device, args.booted)
        if not targets:
            die("no simulators match the filters")
        confirmed = args.yes or args.dry_run or len(targets) == 1 or bool(args.device)

    label = profile_label(mode, keep)
    if not confirmed and sys.stdin.isatty():
        ans = input(f'apply "{label}" to {len(targets)} simulators? [Y/n] ').strip().lower()
        if ans not in ("", "y", "yes"):
            return 1

    preserve = preserve_supported()
    failures = apply_profile(targets, mode, keep, args, preserve)
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
