#!/usr/bin/env python3
"""
Drive WLED effect speed (SX) from a YouTube heatmap, in sync with playback.

Reads a heatmap JSON (buckets of {start_time, end_time, value}), interpolates
between buckets, and pushes SX to WLED on a timer keyed to elapsed wall time.

Stdlib only.

  python3 heatmap_speed.py --ip 192.168.1.12 --file heatmap.json
  python3 heatmap_speed.py --ip 192.168.1.12 --dry-run --rate 0.25
  python3 heatmap_speed.py --ip 192.168.1.12 --start-at 90    # resume mid-video
"""

import argparse, json, sys, time, urllib.request, urllib.error

# --------------------------------------------------------------------------
# mapping
# --------------------------------------------------------------------------

def load_buckets(path):
    with open(path) as f:
        data = json.load(f)
    buckets = data["heatmap"] if isinstance(data, dict) else data
    buckets.sort(key=lambda b: b["start_time"])
    return buckets


def value_at(buckets, t):
    """Linearly interpolate the heatmap value at time t (seconds)."""
    if t <= buckets[0]["start_time"]:
        return buckets[0]["value"]
    if t >= buckets[-1]["end_time"]:
        return buckets[-1]["value"]

    # interpolate between bucket midpoints so the curve is smooth, not stepped
    mids = [((b["start_time"] + b["end_time"]) / 2.0, b["value"]) for b in buckets]
    if t <= mids[0][0]:
        return mids[0][1]
    for (t0, v0), (t1, v1) in zip(mids, mids[1:]):
        if t0 <= t <= t1:
            f = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return v0 + f * (v1 - v0)
    return mids[-1][1]


def to_sx(value, lo, hi, gamma):
    """Map a 0..1 heatmap value to an SX byte, with optional curve shaping."""
    v = max(0.0, min(1.0, value)) ** gamma
    return int(round(lo + v * (hi - lo)))


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------

def send(ip, sx, ix=None, timeout=1.0):
    """One /win call. &NN suppresses UDP sync so this doesn't flood other boards."""
    url = "http://%s/win&SX=%d&NN" % (ip, sx)
    if ix is not None:
        url = "http://%s/win&SX=%d&IX=%d&NN" % (ip, sx, ix)
    try:
        urllib.request.urlopen(url, timeout=timeout).read()
        return True
    except (urllib.error.URLError, OSError) as e:
        print("  ! %s" % e, file=sys.stderr)
        return False


# --------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--ip", required=True, help="WLED address, e.g. 192.168.1.12")
    p.add_argument("--file", default="heatmap.json")
    p.add_argument("--rate", type=float, default=1.0,
                   help="seconds between updates (default 1.0)")
    p.add_argument("--sx-min", type=int, default=40)
    p.add_argument("--sx-max", type=int, default=255)
    p.add_argument("--gamma", type=float, default=1.0,
                   help=">1 compresses the low end, <1 expands it")
    p.add_argument("--intensity", action="store_true",
                   help="also drive IX from the same curve")
    p.add_argument("--start-at", type=float, default=0.0,
                   help="video position to start from, seconds")
    p.add_argument("--deadband", type=int, default=2,
                   help="skip the request if SX moved less than this")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()

    buckets = load_buckets(a.file)
    duration = buckets[-1]["end_time"]
    print("%d buckets, %.1fs (%d:%02d)" % (
        len(buckets), duration, duration // 60, duration % 60))
    print("SX range %d-%d, update every %.2fs, gamma %.2f"
          % (a.sx_min, a.sx_max, a.rate, a.gamma))

    if not a.dry_run:
        input("\nStart the video, then press Enter... ")

    t_zero = time.monotonic() - a.start_at
    last_sx = None
    sent = skipped = 0

    while True:
        t = time.monotonic() - t_zero
        if t > duration:
            break

        v = value_at(buckets, t)
        sx = to_sx(v, a.sx_min, a.sx_max, a.gamma)
        ix = sx if a.intensity else None

        if last_sx is not None and abs(sx - last_sx) < a.deadband:
            skipped += 1
        else:
            if a.dry_run:
                bar = "#" * int(v * 40)
                print("%6.1fs  v=%.3f  SX=%3d  %s" % (t, v, sx, bar))
            else:
                send(a.ip, sx, ix)
            last_sx = sx
            sent += 1

        if a.dry_run:
            t_zero -= a.rate          # fast-forward instead of sleeping
        else:
            time.sleep(a.rate)

    print("\ndone — %d requests sent, %d skipped by deadband" % (sent, skipped))


if __name__ == "__main__":
    main()
