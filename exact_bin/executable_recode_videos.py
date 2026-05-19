#!/usr/bin/env python3
"""Smart batch video recoder targeting HEVC.

Walks a directory of mixed video sources, probes each file, picks per-file
encoding parameters from a quality tier (standard / high / ultra), and writes
smaller HEVC outputs. Run with --help for the full CLI.
"""

import argparse
import csv
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_EXTS = {".mp4", ".mov", ".mkv", ".m4v", ".avi"}
PARTIAL_SUFFIX = ".partial.mp4"

# Tier configuration. Every tier emits HEVC into an MP4 container with hvc1 tag.
# `bpp` is bits per pixel per frame. Target bitrate = bpp * W * H * fps.
# - standard (HW HEVC, bitrate-mode) needs more bits than libx265 at the same
#   quality, hence a higher bpp.
# - high  (libx265 crf=22) is the quality-targeted middle tier; bpp here is used
#   only for the smart-skip projection and as the basis of the -maxrate cap.
# - ultra (libx265 crf=18) is near-visually-lossless; same notes as high.
# `speed_at_1080p` is a rough Apple-Silicon throughput multiplier (output seconds
# of video per wall second) at 1920x1080. Used only by --probe for an encode-time
# forecast; it scales inversely with pixel count, so 4K is ~4x slower.
TIERS = {
    "standard": {
        "encoder": "hevc_videotoolbox",
        "mode": "bitrate",
        "bpp": 0.075,
        "preset": None,
        "crf": None,
        "speed_at_1080p": 3.0,
    },
    "high": {
        "encoder": "libx265",
        "mode": "crf",
        "bpp": 0.050,
        "preset": "medium",
        "crf": 22,
        "speed_at_1080p": 0.8,
    },
    "ultra": {
        "encoder": "libx265",
        "mode": "crf",
        "bpp": 0.090,
        "preset": "slow",
        "crf": 18,
        "speed_at_1080p": 0.3,
    },
}

REF_PIXELS_1080P = 1920 * 1080

MIN_TARGET_BPS = 1_500_000
MAX_TARGET_BPS = 60_000_000

# Empirical bitrate ratio: HEVC bits needed per source-codec bit at equivalent
# visual quality. <1.0 means HEVC saves space at the same quality. Used to
# project CRF-mode output, since CRF is quality-driven and the encoder doesn't
# honor `tgt` as a target — only as a maxrate ceiling.
HEVC_EFFICIENCY = {
    "h264": 0.55,
    "vp8": 0.55,
    "vp9": 0.85,
    "mpeg4": 0.40,
    "msmpeg4v3": 0.35,
    "mpeg2video": 0.35,
    "mpeg1video": 0.30,
    "wmv3": 0.45,
}
DEFAULT_HEVC_EFFICIENCY = 0.60

IS_TTY = sys.stdout.isatty()
USE_COLOR = IS_TTY and os.environ.get("TERM") != "dumb"


class C:
    RESET = "\x1b[0m" if USE_COLOR else ""
    DIM = "\x1b[2m" if USE_COLOR else ""
    BOLD = "\x1b[1m" if USE_COLOR else ""
    RED = "\x1b[31m" if USE_COLOR else ""
    GREEN = "\x1b[32m" if USE_COLOR else ""
    YELLOW = "\x1b[33m" if USE_COLOR else ""
    CYAN = "\x1b[36m" if USE_COLOR else ""


def fmt_bytes(n: float) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    f = float(n)
    while f >= 1024 and i < len(units) - 1:
        f /= 1024
        i += 1
    return f"{f:.1f} {units[i]}"


def fmt_bps(n: float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f} Mbps"
    if n >= 1_000:
        return f"{n / 1_000:.0f} kbps"
    return f"{n:.0f} bps"


def fmt_duration(s: float) -> str:
    s = int(round(s))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


@dataclass
class ProbeInfo:
    path: Path
    video_codec: str
    codec_tag: str
    width: int
    height: int
    pix_fmt: str
    color_range: str
    color_space: Optional[str]
    color_primaries: Optional[str]
    color_transfer: Optional[str]
    fps: float
    bit_rate: float
    duration: float
    audio_codec: Optional[str]
    audio_bitrate: Optional[float]
    size: int

    def effective_fps(self) -> float:
        """fps used for bitrate math (defaults to 30 if probe failed)."""
        return self.fps if self.fps > 0 else 30.0

    def short_desc(self) -> str:
        return (f"{self.video_codec} {self.width}x{self.height} "
                f"{fmt_bps(self.bit_rate)}  {self.duration:.1f} s  "
                f"{fmt_bytes(self.size)}")


def probe(path: Path) -> Optional[ProbeInfo]:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_streams", "-show_format", str(path)],
            check=True, capture_output=True, text=True,
        ).stdout
        data = json.loads(out)
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError):
        return None
    v = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v:
        return None
    a = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), None)
    fmt = data.get("format", {})
    try:
        size = int(fmt.get("size") or path.stat().st_size)
    except OSError:
        return None
    try:
        duration = float(v.get("duration") or fmt.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    br_video = v.get("bit_rate")
    br_fmt = fmt.get("bit_rate")
    if br_video:
        bit_rate = float(br_video)
    elif br_fmt:
        bit_rate = float(br_fmt)
    elif duration > 0:
        bit_rate = size * 8.0 / duration
    else:
        bit_rate = 0.0
    fps = 0.0
    rf = v.get("avg_frame_rate") or v.get("r_frame_rate") or "0/1"
    try:
        num, den = rf.split("/")
        if float(den) > 0:
            fps = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    pix_fmt = v.get("pix_fmt", "")
    color_range = v.get("color_range") or ("pc" if pix_fmt.startswith("yuvj") else "tv")
    audio_codec = a.get("codec_name") if a else None
    audio_br = None
    if a and a.get("bit_rate"):
        try:
            audio_br = float(a["bit_rate"])
        except (TypeError, ValueError):
            audio_br = None
    return ProbeInfo(
        path=path,
        video_codec=v.get("codec_name", "?"),
        codec_tag=(v.get("codec_tag_string") or "").lower(),
        width=int(v.get("width", 0)),
        height=int(v.get("height", 0)),
        pix_fmt=pix_fmt,
        color_range=color_range,
        color_space=v.get("color_space"),
        color_primaries=v.get("color_primaries"),
        color_transfer=v.get("color_transfer"),
        fps=fps,
        bit_rate=bit_rate,
        duration=duration,
        audio_codec=audio_codec,
        audio_bitrate=audio_br,
        size=size,
    )


def target_bitrate(info: ProbeInfo, tier_name: str) -> float:
    raw = (TIERS[tier_name]["bpp"]
           * info.width * info.height * info.effective_fps())
    return max(MIN_TARGET_BPS, min(MAX_TARGET_BPS, raw))


def estimate_output_bitrate(info: ProbeInfo, tier_name: str) -> float:
    """Predicted HEVC output bitrate this tier will produce for this source.

    For bitrate-mode tiers (standard) the encoder targets `tgt` directly, so
    that's the estimate. For CRF-mode tiers (high/ultra) quality is fixed and
    actual bitrate scales with source content; we model it as
    source_bitrate * codec_efficiency, since HEVC at matched quality typically
    needs ~55% of H.264, ~40% of MPEG-4, etc. The bpp-based `tgt` is not used
    as a CRF estimate because it can be far above what CRF actually produces
    for low-bitrate sources.
    """
    tier = TIERS[tier_name]
    tgt = target_bitrate(info, tier_name)
    if tier["mode"] == "bitrate":
        return tgt
    if info.bit_rate <= 0:
        return tgt
    factor = HEVC_EFFICIENCY.get(info.video_codec, DEFAULT_HEVC_EFFICIENCY)
    return info.bit_rate * factor


def estimate_encode_seconds(info: ProbeInfo, tier_name: str) -> float:
    """Rough wall-time forecast for --probe. Inversely scales with pixels."""
    speed = TIERS[tier_name]["speed_at_1080p"]
    pixels = max(1, info.width * info.height)
    pixel_factor = pixels / REF_PIXELS_1080P
    effective_speed = speed / pixel_factor
    if effective_speed <= 0:
        return info.duration
    return info.duration / effective_speed


def decide(info: ProbeInfo, tier: str, policy: str, min_savings_pct: float):
    if policy == "always":
        return "recode", ""
    # Destination codec match: skip. HEVC is what we'd write; AV1 is strictly more
    # efficient than our target. Re-encoding either is almost always a loss
    # (quality drop with no meaningful size win). Use --encoding-policy always to
    # force.
    if info.video_codec == "hevc":
        # hvc1 tag is what this script writes, so it's a strong "already
        # processed by us" signal worth surfacing in the reason.
        marker = " (hvc1)" if info.codec_tag == "hvc1" else ""
        return ("skip-efficient",
                f"already HEVC{marker} {fmt_bps(info.bit_rate)}")
    if info.video_codec == "av1":
        return ("skip-efficient",
                f"already AV1 {fmt_bps(info.bit_rate)}")
    if info.bit_rate <= 0:
        return "recode", ""
    # Compare against the codec-efficiency-adjusted estimate, not raw `tgt`.
    # A 2 Mbps H.264 source can still shrink under HEVC CRF because HEVC needs
    # roughly half the bitrate at the same visual quality; comparing raw `tgt`
    # to source bitrate would wrongly mark such files as "bump up".
    est_bps = estimate_output_bitrate(info, tier)
    projected = (1 - est_bps / info.bit_rate) * 100
    if projected < min_savings_pct:
        return ("skip-efficient",
                f"low projected savings {projected:.0f}% "
                f"({fmt_bps(info.bit_rate)} → {fmt_bps(est_bps)})")
    return "recode", ""


def build_ffmpeg_cmd(info: ProbeInfo, tier_name: str, out_path: Path) -> list:
    tier = TIERS[tier_name]
    tgt = target_bitrate(info, tier_name)
    cmd = [
        "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
        "-nostats", "-progress", "pipe:1", "-y",
        "-i", str(info.path),
        "-map", "0:v:0",
    ]
    if info.audio_codec:
        cmd += ["-map", "0:a:0?"]
    cmd += ["-c:v", tier["encoder"]]
    if tier["mode"] == "bitrate":
        cmd += [
            "-b:v", str(int(tgt)),
            "-maxrate", str(int(tgt * 1.5)),
            "-bufsize", str(int(tgt * 3)),
        ]
    else:
        cmd += [
            "-preset", tier["preset"],
            "-crf", str(tier["crf"]),
            "-maxrate", str(int(tgt * 2)),
            "-bufsize", str(int(tgt * 4)),
        ]
    cmd += ["-tag:v", "hvc1"]
    # Pixel format / color range. yuvj420p (full range) must be range-converted,
    # not just retagged — otherwise highlights and blacks shift.
    if info.pix_fmt.startswith("yuvj"):
        cmd += ["-vf", "scale=in_range=full:out_range=limited:flags=accurate_rnd"]
    cmd += ["-pix_fmt", "yuv420p", "-color_range", "tv"]
    if info.color_space:
        cmd += ["-colorspace", info.color_space]
    if info.color_primaries:
        cmd += ["-color_primaries", info.color_primaries]
    if info.color_transfer:
        cmd += ["-color_trc", info.color_transfer]
    if info.audio_codec:
        keep_aac = info.audio_codec == "aac" and (info.audio_bitrate or 0) <= 192_000
        if keep_aac:
            cmd += ["-c:a", "copy"]
        else:
            cmd += ["-c:a", "aac", "-b:a", "128k", "-ac", "2"]
    cmd += [
        "-map_metadata", "0",
        "-movflags", "+faststart+use_metadata_tags",
        str(out_path),
    ]
    return cmd


def _parse_out_time(v: str) -> Optional[int]:
    """Parse ffmpeg's out_time HH:MM:SS.uuuuuu into microseconds."""
    try:
        h, m, rest = v.split(":")
        sec, _, us = rest.partition(".")
        return ((int(h) * 3600 + int(m) * 60 + int(sec)) * 1_000_000
                + int((us + "000000")[:6]))
    except (ValueError, IndexError):
        return None


def run_encode(cmd: list, info: ProbeInfo, label: str):
    """Run ffmpeg with -progress on stdout. Returns (ok, stderr_tail)."""
    start = time.monotonic()
    duration_us = max(1, int(info.duration * 1_000_000))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
    )
    last_render = 0.0
    cur_us = 0
    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            line = line.strip()
            if not line or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k == "out_time":
                parsed = _parse_out_time(v)
                if parsed is not None:
                    cur_us = parsed
            if not IS_TTY:
                continue
            now = time.monotonic()
            if now - last_render < 0.2 and k != "progress":
                continue
            last_render = now
            pct = min(99, cur_us * 100 // duration_us)
            elapsed = now - start
            speed = (cur_us / 1_000_000) / elapsed if elapsed > 0 else 0
            eta = (duration_us - cur_us) / 1_000_000 / speed if speed > 0 else 0
            msg = (f"        {C.CYAN}▶{C.RESET}  {label}   "
                   f"{pct:3d}% · {speed:.1f}x · ETA {fmt_duration(eta)}")
            sys.stdout.write("\r\x1b[2K" + msg)
            sys.stdout.flush()
        err = proc.stderr.read() if proc.stderr else ""  # type: ignore[union-attr]
        rc = proc.wait()
    finally:
        if IS_TTY:
            sys.stdout.write("\r\x1b[2K")
            sys.stdout.flush()
    tail = "\n".join(err.strip().splitlines()[-20:]) if err else ""
    return rc == 0, tail


def verify_output(src: ProbeInfo, dst: Path):
    if not dst.exists() or dst.stat().st_size == 0:
        return False, "output missing or empty"
    out = probe(dst)
    if out is None:
        return False, "output unreadable"
    if out.duration <= 0:
        return False, "output duration is zero"
    if abs(out.duration - src.duration) > 0.5:
        return False, (f"duration mismatch: src {src.duration:.2f}s "
                       f"vs out {out.duration:.2f}s")
    return True, ""


def find_videos(root: Path, exts: set, recursive: bool = False) -> list:
    result = []
    iterator = root.rglob("*") if recursive else root.glob("*")
    for p in sorted(iterator):
        if not p.is_file() or p.name.startswith("."):
            continue
        if PARTIAL_SUFFIX in p.name:
            continue
        if p.suffix.lower() in exts:
            result.append(p)
    return result


def output_path_for(src: Path, in_root: Path, out_root: Path) -> Path:
    rel = src.relative_to(in_root)
    return (out_root / rel).with_suffix(".mp4")


def run_probe(files: list, in_root: Path, args) -> int:
    """Read-only forecast: probe each file, apply decision logic, report
    estimated output size, encode time, and aggregate savings. No encoding."""
    csv_writer = None
    csv_fh = None
    if args.log_csv:
        csv_fh = open(args.log_csv, "w", newline="")
        csv_writer = csv.writer(csv_fh)
        csv_writer.writerow([
            "path", "decision", "src_codec", "src_w", "src_h", "src_bitrate",
            "target_bitrate", "src_bytes", "estimated_dst_bytes",
            "estimated_savings_pct", "estimated_encode_seconds", "reason",
        ])

    tier = TIERS[args.quality]
    counts = {"recode": 0, "skip-efficient": 0, "unreadable": 0}
    total_src_bytes = 0
    total_dst_bytes = 0
    total_encode_seconds = 0.0

    print(f"{C.BOLD}probe · quality={args.quality} · policy={args.encoding_policy}"
          f"{C.RESET}")
    print()
    for idx, src in enumerate(files, 1):
        rel = src.relative_to(in_root) if in_root in src.parents or src == in_root else src.name
        header = f"[{idx}/{len(files)}] {rel}"
        info = probe(src)
        if info is None:
            print(f"{header}   {C.RED}unreadable{C.RESET}")
            counts["unreadable"] += 1
            if csv_writer:
                csv_writer.writerow([str(src), "unreadable", "", "", "", "",
                                     "", "", "", "", "", "probe failed"])
            continue

        decision, reason = decide(info, args.quality, args.encoding_policy,
                                  args.min_savings_pct)
        tgt = target_bitrate(info, args.quality)

        if decision == "skip-efficient":
            counts["skip-efficient"] += 1
            total_src_bytes += info.size
            total_dst_bytes += info.size  # unchanged on skip
            print(f"{header}   {C.DIM}skip{C.RESET}   "
                  f"{info.video_codec} {info.width}x{info.height} "
                  f"{fmt_bps(info.bit_rate)} · {fmt_bytes(info.size)}   "
                  f"({reason})")
            if csv_writer:
                csv_writer.writerow([
                    str(src), decision, info.video_codec, info.width, info.height,
                    int(info.bit_rate), int(tgt), info.size, info.size, "0.0",
                    "0.0", reason,
                ])
            continue

        # recode forecast — use the same codec-efficiency-adjusted estimate
        # that decide() used, so probe predictions and skip decisions agree.
        est_bps = estimate_output_bitrate(info, args.quality)
        est_bytes = int(est_bps * info.duration / 8) if info.duration > 0 else info.size
        # Also include AAC audio bitrate when source was uncompressed (rough).
        if info.audio_codec and info.audio_codec != "aac":
            est_bytes += int(128_000 * info.duration / 8)
        # Don't claim the output will be larger than the source.
        if est_bytes > info.size:
            est_bytes = info.size
        savings_pct = (1 - est_bytes / info.size) * 100 if info.size > 0 else 0
        est_seconds = estimate_encode_seconds(info, args.quality)

        counts["recode"] += 1
        total_src_bytes += info.size
        total_dst_bytes += est_bytes
        total_encode_seconds += est_seconds

        if tier["mode"] == "crf":
            tier_label = f"libx265 crf={tier['crf']}"
        else:
            tier_label = f"hevc_videotoolbox {fmt_bps(tgt)}"
        print(f"{header}")
        print(f"        {C.DIM}src:{C.RESET} {info.short_desc()}")
        print(f"        {C.CYAN}≈{C.RESET}   {args.quality} · {tier_label}   "
              f"out ≈ {fmt_bytes(est_bytes)} · −{savings_pct:.1f} % · "
              f"encode ≈ {fmt_duration(est_seconds)}")

        if csv_writer:
            csv_writer.writerow([
                str(src), "recode", info.video_codec, info.width, info.height,
                int(info.bit_rate), int(tgt), info.size, est_bytes,
                f"{savings_pct:.1f}", f"{est_seconds:.1f}", "",
            ])

    saved = total_src_bytes - total_dst_bytes
    saved_pct = (saved / total_src_bytes * 100) if total_src_bytes else 0

    print()
    print(f"{C.BOLD}probe summary{C.RESET}")
    print(f"  {len(files)} files · "
          f"{C.GREEN}recode {counts['recode']}{C.RESET} · "
          f"{C.DIM}skip {counts['skip-efficient']}{C.RESET} · "
          f"{C.RED}unreadable {counts['unreadable']}{C.RESET}")
    print(f"  source total:        {fmt_bytes(total_src_bytes)}")
    print(f"  projected output:    {fmt_bytes(total_dst_bytes)}")
    print(f"  projected savings:   {fmt_bytes(saved)}  (−{saved_pct:.1f} %)")
    print(f"  projected encode:    {fmt_duration(total_encode_seconds)}   "
          f"{C.DIM}(rough; Apple-Silicon throughput model){C.RESET}")
    if csv_fh:
        csv_fh.close()
    return 0


_SHELL_SAFE = re.compile(r"^[A-Za-z0-9_@%+=:,./-]+$")


def _shell_quote(s: str) -> str:
    if _SHELL_SAFE.match(s):
        return s
    return "'" + s.replace("'", "'\\''") + "'"


def plan_tasks(files, in_root, args, single_file_mode, single_out_file, out_root):
    """Pre-scan: probe every file and decide its outcome up front, so the main
    loop has nothing to discover and we can report total recode count + ETA
    before encoding starts. Mirrors the decision logic in the encoder loop."""
    tasks = []
    n_recode = n_skip_eff = n_skip_exist = n_unreadable = 0
    total_est = 0.0
    for src in files:
        info = probe(src)
        if info is None:
            tasks.append({"src": src, "info": None, "decision": "unreadable",
                          "reason": "", "final_dst": None, "est_seconds": 0.0})
            n_unreadable += 1
            continue
        if args.replace:
            final_dst = src
        elif single_file_mode:
            final_dst = single_out_file
        else:
            final_dst = output_path_for(src, in_root, out_root)
        if not args.replace and not args.force and final_dst.exists():
            tasks.append({"src": src, "info": info, "decision": "skip-existing",
                          "reason": "output exists", "final_dst": final_dst,
                          "est_seconds": 0.0})
            n_skip_exist += 1
            continue
        decision, reason = decide(info, args.quality, args.encoding_policy,
                                  args.min_savings_pct)
        if decision == "skip-efficient":
            tasks.append({"src": src, "info": info, "decision": "skip-efficient",
                          "reason": reason, "final_dst": final_dst,
                          "est_seconds": 0.0})
            n_skip_eff += 1
            continue
        est = estimate_encode_seconds(info, args.quality)
        tasks.append({"src": src, "info": info, "decision": "recode",
                      "reason": "", "final_dst": final_dst, "est_seconds": est})
        n_recode += 1
        total_est += est
    counts = {"recode": n_recode, "skip-efficient": n_skip_eff,
              "skip-existing": n_skip_exist, "unreadable": n_unreadable}
    return tasks, counts, total_est


def main() -> int:
    ap = argparse.ArgumentParser(
        description=("Smart batch video recoder (HEVC). Picks per-file encoding "
                     "params and writes smaller files. Input can be a single "
                     "video file or a directory (recursed)."),
    )
    ap.add_argument("-i", "--input", type=Path, dest="input", required=True,
                    help="Input file or directory (directories are recursed).")
    ap.add_argument("-o", "--output", type=Path, dest="output",
                    help="Output path. For a directory input, this is the "
                         "destination directory (tree is mirrored). For a "
                         "single-file input, this may be a target file path or "
                         "an existing directory. Mutually exclusive with --replace.")
    ap.add_argument("--quality", choices=["standard", "high", "ultra"], default="high")
    ap.add_argument("--encoding-policy", choices=["smart", "always"], default="smart")
    ap.add_argument("--replace", action="store_true",
                    help="Overwrite source after verify (original is lost).")
    ap.add_argument("-r", "--recursive", action="store_true",
                    help="Recurse into subdirectories of --input. Directory "
                         "mode only; off by default.")
    ap.add_argument("--include-ext", default=",".join(sorted(DEFAULT_EXTS)),
                    help="Comma-separated extensions (with dots). Directory mode only.")
    ap.add_argument("--min-savings-pct", type=float, default=15.0)
    ap.add_argument("--dry-run", action="store_true",
                    help="Print decisions and the exact ffmpeg command; "
                         "encode nothing.")
    ap.add_argument("--probe", action="store_true",
                    help="Read-only forecast: probes every file, applies the "
                         "decision logic, and reports estimated output size, "
                         "estimated encode time, and aggregate savings. "
                         "Encodes nothing; --output / --replace not required.")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--log-csv", type=Path)
    args = ap.parse_args()

    input_path = args.input
    if not input_path.exists():
        print(f"error: {input_path} does not exist", file=sys.stderr)
        return 2

    if not args.probe:
        if not args.replace and not args.output:
            print("error: either --replace or --output is required "
                  "(or use --probe for a read-only forecast)", file=sys.stderr)
            return 2
        if args.replace and args.output:
            print("warning: --replace given; ignoring --output", file=sys.stderr)
            args.output = None

    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            print(f"error: {tool} not found on PATH", file=sys.stderr)
            return 2

    exts = set()
    for e in args.include_ext.split(","):
        e = e.strip().lower()
        if not e:
            continue
        exts.add(e if e.startswith(".") else "." + e)

    single_file_mode = input_path.is_file()
    if single_file_mode:
        in_root = input_path.resolve().parent
        files = [input_path.resolve()]
    else:
        in_root = input_path.resolve()
        files = find_videos(in_root, exts, recursive=args.recursive)

    # Resolve output root / single-file destination
    out_root: Optional[Path] = None
    single_out_file: Optional[Path] = None
    if args.output:
        out = args.output.resolve()
        if single_file_mode:
            # If --output points to an existing directory, drop the file inside.
            # Otherwise treat it as the literal output file path.
            if out.is_dir():
                single_out_file = (out / files[0].name).with_suffix(".mp4")
            else:
                single_out_file = out if out.suffix else out.with_suffix(".mp4")
        else:
            out_root = out

    if not files:
        print("no video files found")
        return 0

    if args.probe:
        return run_probe(files, in_root, args)

    print(f"pre-scan: probing {len(files)} files...", flush=True)
    tasks, plan_counts, total_est_seconds = plan_tasks(
        files, in_root, args, single_file_mode, single_out_file, out_root)
    n_recode = plan_counts["recode"]
    parts = [f"{C.GREEN}recode {n_recode}{C.RESET}",
             f"{C.DIM}skip-efficient {plan_counts['skip-efficient']}{C.RESET}",
             f"{C.DIM}skip-existing {plan_counts['skip-existing']}{C.RESET}"]
    if plan_counts["unreadable"]:
        parts.append(f"{C.RED}unreadable {plan_counts['unreadable']}{C.RESET}")
    plan_line = "plan: " + " · ".join(parts)
    if n_recode:
        plan_line += f"   ETA {fmt_duration(total_est_seconds)}"
    print(plan_line)

    csv_writer = None
    csv_fh = None
    if args.log_csv:
        csv_fh = open(args.log_csv, "w", newline="")
        csv_writer = csv.writer(csv_fh)
        csv_writer.writerow([
            "path", "decision", "src_codec", "src_w", "src_h", "src_bitrate",
            "dst_bitrate", "src_bytes", "dst_bytes", "savings_pct",
            "encode_seconds", "status", "error_tail",
        ])

    summary = {"recoded": 0, "skipped-efficient": 0,
               "skipped-existing": 0, "failed": 0}
    total_src_bytes = 0
    total_dst_bytes = 0
    wall_start = time.monotonic()

    interrupted = False

    def handle_sigint(_sig, _frm):
        nonlocal interrupted
        interrupted = True

    signal.signal(signal.SIGINT, handle_sigint)

    # ETA calibration state. `remaining_est` is the unused portion of the
    # original pre-scan estimate; `cal_actual / cal_est` is the running ratio
    # of measured to predicted encode time across completed recodes, used to
    # rescale the remaining estimate so the displayed ETA tracks reality.
    remaining_est = total_est_seconds
    cal_actual = 0.0
    cal_est = 0.0
    recodes_done = 0

    def emit_eta():
        if recodes_done >= n_recode:
            return
        factor = (cal_actual / cal_est) if cal_est > 0 else 1.0
        eta = remaining_est * factor
        print(f"        {C.DIM}remaining: {n_recode - recodes_done} files · "
              f"ETA {fmt_duration(eta)} (×{factor:.2f}){C.RESET}")

    for idx, task in enumerate(tasks, 1):
        if interrupted:
            print("\ninterrupted by user.")
            break
        src = task["src"]
        info = task["info"]
        rel = src.relative_to(in_root)
        header = f"[{idx}/{len(tasks)}] {rel}"

        if task["decision"] == "unreadable":
            print(f"{header}   {C.RED}skip{C.RESET} (unreadable)")
            summary["failed"] += 1
            continue

        if task["decision"] == "skip-existing":
            print(f"{header}   {C.DIM}skip{C.RESET} (output exists)")
            summary["skipped-existing"] += 1
            continue

        if task["decision"] == "skip-efficient":
            reason = task["reason"]
            print(f"{header}   {C.DIM}skip{C.RESET} ({reason})")
            summary["skipped-efficient"] += 1
            if csv_writer:
                csv_writer.writerow([
                    str(src), "skip-efficient", info.video_codec, info.width,
                    info.height, int(info.bit_rate), "", info.size, "", "", "",
                    reason, "",
                ])
            continue

        # decision == "recode"
        # Keep the source's exact path on --replace (incl. extension case). The
        # encoder writes MP4 into `partial`; after verify + rename, partial
        # takes src's path. Using src.with_suffix(".mp4") would point at a
        # different path on case-sensitive volumes and could clobber an
        # unrelated pre-existing file.
        final_dst = task["final_dst"]
        est_seconds = task["est_seconds"]
        tier = TIERS[args.quality]
        tgt = target_bitrate(info, args.quality)
        if tier["mode"] == "crf":
            label = f"{args.quality} · libx265 crf={tier['crf']}"
        else:
            label = f"{args.quality} · hevc_videotoolbox {fmt_bps(tgt)}"

        print(f"{header}   {C.DIM}[recode {recodes_done + 1}/{n_recode}]{C.RESET}")
        print(f"        {C.DIM}src:{C.RESET} {info.short_desc()}")

        if args.replace:
            partial = src.with_name(f".{src.stem}{PARTIAL_SUFFIX}")
        else:
            final_dst.parent.mkdir(parents=True, exist_ok=True)
            partial = final_dst.with_name(f".{final_dst.stem}{PARTIAL_SUFFIX}")

        cmd = build_ffmpeg_cmd(info, args.quality, partial)

        if args.dry_run:
            print(f"        {C.CYAN}DRY{C.RESET}  {label}   →   {final_dst}")
            print(f"        {C.DIM}{' '.join(_shell_quote(c) for c in cmd)}{C.RESET}")
            continue

        if partial.exists():
            try:
                partial.unlink()
            except OSError:
                pass

        t0 = time.monotonic()
        ok, err_tail = run_encode(cmd, info, label)
        elapsed = time.monotonic() - t0

        # Every recode attempt — success or failure — consumes its share of
        # the original pre-scan estimate. Failures don't feed the calibration
        # ratio because their elapsed time isn't a representative sample of
        # successful encode speed.
        recodes_done += 1
        remaining_est = max(0.0, remaining_est - est_seconds)

        if not ok:
            try:
                if partial.exists():
                    partial.unlink()
            except OSError:
                pass
            print(f"        {C.RED}✗  failed after {fmt_duration(elapsed)}{C.RESET}")
            for line in err_tail.splitlines()[-5:]:
                print(f"           {C.DIM}{line}{C.RESET}")
            summary["failed"] += 1
            if csv_writer:
                csv_writer.writerow([
                    str(src), "failed", info.video_codec, info.width, info.height,
                    int(info.bit_rate), int(tgt), info.size, 0, "",
                    f"{elapsed:.1f}", "encode failed",
                    err_tail.replace("\n", " | ")[:500],
                ])
            emit_eta()
            continue

        verified, vreason = verify_output(info, partial)
        if not verified:
            try:
                partial.unlink()
            except OSError:
                pass
            print(f"        {C.RED}✗  verify failed: {vreason}{C.RESET}")
            summary["failed"] += 1
            if csv_writer:
                csv_writer.writerow([
                    str(src), "failed", info.video_codec, info.width, info.height,
                    int(info.bit_rate), int(tgt), info.size, 0, "",
                    f"{elapsed:.1f}", f"verify failed: {vreason}", "",
                ])
            emit_eta()
            continue

        dst_size = partial.stat().st_size
        if dst_size >= info.size and not args.force:
            try:
                partial.unlink()
            except OSError:
                pass
            savings = (1 - dst_size / info.size) * 100 if info.size else 0
            print(f"        {C.YELLOW}!  output not smaller "
                  f"({fmt_bytes(dst_size)}); discarded{C.RESET}")
            summary["skipped-efficient"] += 1
            # The encode itself ran to completion, so feed calibration even
            # though we're discarding the output.
            cal_actual += elapsed
            cal_est += est_seconds
            if csv_writer:
                csv_writer.writerow([
                    str(src), "skip-not-smaller", info.video_codec,
                    info.width, info.height, int(info.bit_rate), int(tgt),
                    info.size, dst_size, f"{savings:.1f}", f"{elapsed:.1f}",
                    "discarded: not smaller", "",
                ])
            emit_eta()
            continue

        if args.replace:
            # Atomic overwrite — rename(2) on POSIX, so src points at either
            # the old inode or the new one, never a partial write. Verify
            # above has already confirmed the partial is good.
            try:
                partial.replace(final_dst)
            except OSError as e:
                print(f"        {C.RED}✗  overwrite failed: {e}. "
                      f"Partial at {partial}{C.RESET}")
                summary["failed"] += 1
                emit_eta()
                continue
        else:
            try:
                partial.rename(final_dst)
            except OSError as e:
                print(f"        {C.RED}✗  rename failed: {e}{C.RESET}")
                summary["failed"] += 1
                emit_eta()
                continue

        savings = (1 - dst_size / info.size) * 100 if info.size else 0
        sign = "−" if savings >= 0 else "+"
        print(f"        {C.GREEN}✓{C.RESET}  done {fmt_duration(elapsed)} · "
              f"{fmt_bytes(info.size)} → {fmt_bytes(dst_size)} · "
              f"{sign}{abs(savings):.1f} %")
        summary["recoded"] += 1
        total_src_bytes += info.size
        total_dst_bytes += dst_size
        cal_actual += elapsed
        cal_est += est_seconds
        if csv_writer:
            csv_writer.writerow([
                str(src), "recoded", info.video_codec, info.width, info.height,
                int(info.bit_rate), int(tgt), info.size, dst_size,
                f"{savings:.1f}", f"{elapsed:.1f}", "ok", "",
            ])
        emit_eta()

    wall = time.monotonic() - wall_start
    saved = total_src_bytes - total_dst_bytes
    pct = (saved / total_src_bytes * 100) if total_src_bytes else 0
    print()
    print(f"{len(files)} files · "
          f"{C.GREEN}recoded {summary['recoded']}{C.RESET} · "
          f"{C.DIM}skipped-efficient {summary['skipped-efficient']}{C.RESET} · "
          f"{C.DIM}skipped-existing {summary['skipped-existing']}{C.RESET} · "
          f"{C.RED}failed {summary['failed']}{C.RESET}")
    if summary["recoded"]:
        print(f"saved {fmt_bytes(saved)} (−{pct:.1f} %) · "
              f"wall time {fmt_duration(wall)}")
    else:
        print(f"wall time {fmt_duration(wall)}")
    if csv_fh:
        csv_fh.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
