# -*- coding: utf-8 -*-
"""
PEARL_ANIM v4: apply the client notes of 2026-10-02 to untitled_water_realism_v001.hiplc

    1. main lights dim 100 % -> 15 % (not to black) with a small ramp in / ramp out
    2. the tree lights are untouched
    3. the flicker sits on the beat grid (150 BPM = 45 beats per 540-frame loop by default; set the
       real BPM on /obj/PEARL_ANIM "Track BPM" once the track is known)
    4. a "hold open" loop variant: shell stays in the open pose, tree keeps looping, lights keep
       flickering; rendered by the new /out/Redshift_ROP_OPEN_LOOP

Run it INSIDE Houdini 21 with the v001 scene loaded (Windows > Python Shell):

    exec(open(r"C:\\path\\to\\apply_v004.py").read())

or from a terminal:

    hython apply_v004.py "C:\\Users\\gtava\\OneDrive\\Desktop\\SARA\\2\\untitled_water_realism_v001.hiplc"

It never overwrites the loaded file: it saves a copy next to it as *_v002.hiplc (or *_v004lights.hiplc
when the name has no _v001).  Every step is idempotent, so running it twice is harmless.
Turn "Hold Shell Open" off and the scene evaluates exactly as before (the script verifies this on
every frame before it swaps the keyframes over).
"""
import os
import re
import sys

import hou

CTRL = "/obj/PEARL_ANIM"
OUT = "/out"
SRC_ROP = "Redshift_ROP_FLICKER"           # copied to make the hold-open ROP
OPEN_ROP = "Redshift_ROP_OPEN_LOOP"
FPS = 30.0

# keyed story channels on the controller that the hold-open toggle overrides:
#   name -> (value while held open, label suffix)
HOLD_OVERRIDES = [
    ("close_amount", 'ch("hold_open_amount")', "shell stays in the open pose"),
    ("pearl_in",     "0",                      "pearl never tucks"),
    ("pearl_out",    "1",                      "pearl stays out (bob / sway / spin keep looping)"),
    ("glow",         "1",                      "glow window open for the whole loop"),
    ("lf_hit",       "0",                      "no slam flash (there is no slam)"),
    ("lf_keyhold",   "0",                      "no key-hold hero moment"),
    ("lf_dipA",      "0",                      "no landing dip"),
    ("lf_dipB",      "0",                      "no landing dip"),
    ("lf_ripple",    "0",                      "no apex ripple"),
]

# v4 parameter values on the controller
V4_VALUES = {
    "fl_blackout_depth": 0.85,   # full-dark blink lands on the 15 % floor instead of black
    "lf_beats": 45.0,            # 45 beats / 540 f @ 30 fps = 150 BPM (the old note said 149 BPM for the 350 f loop)
}

ENGINE_SRC = r'''# ---- PEARL_ANIM per-light flicker (v4, 2026-10-03): beat-locked, 15 % floor, ramped ----
# Levels for [key rslight2, dome6, dome7, grid, water] as multipliers around 1.0 (= steady light).
# All reads are loop-local, so frame loop_start + loop_frames evaluates exactly like loop_start
# (seamless loop).  Each light still strobes on its own seed and swells on its own slow period.
#
# v4 (client notes, 2026-10-02):
#   * floor: no main light goes below lf_floor (0.15).  The full-dark blinks now drop to the floor,
#     not to black (fl_blackout_depth is 0.85 = 1 - floor), and the floor is clamped after everything.
#   * envelope: every dip ramps in over lf_env_attack frames and out over lf_env_release frames
#     instead of switching hard (a small FIR tent, loop-exact).
#   * beat: when lf_beat_sync is on, dips and full-dark blinks start on the beat grid.  The grid is
#     lf_bpm (if > 0) or lf_beats beats per loop, shifted by lf_beat_offset frames, subdivided by
#     lf_beat_div (2 = eighth notes).  Dark dips last lf_beat_darklen frames from the grid frame.
#     Downbeats use the full dark probability, off-beats lf_beat_offbeat of it.
#   * hold_open: the controller forces lf_activity to 1 and the story accents to 0, so the beat
#     flicker simply runs for the whole loop.  Nothing in here needs to know about it.
# v3 (step-based, non-beat) behaviour is kept and used when lf_beat_sync is off.
import math

_PL_NAMES = ("key", "dome6", "dome7", "grid")
_PL_MIX = ("lm_key", "lm_dome6", "lm_dome7", "lm_grid", "lm_water")

# defaults for the v4 parms, used if the controller does not have them (older scene)
_PL_DEFAULTS = {
    "lf_floor": 0.15, "lf_env_attack": 1.0, "lf_env_release": 2.0,
    "lf_beat_sync": 1.0, "lf_bpm": 0.0, "lf_beat_offset": 0.0, "lf_beat_div": 2.0,
    "lf_beat_darklen": 2.0, "lf_beat_offbeat": 0.5, "lf_beat_maxrun": 3.0,
}


def _pl_parm(n, name):
    p = n.parm(name)
    if p is None:
        return _PL_DEFAULTS[name]
    return p.eval()


def _pl_h(seed, s):
    x = math.sin(s * 12.9898 + seed * 78.233) * 43758.5453
    return x - math.floor(x)


def _pl_swell(i, L, period, seed):
    # smooth noise around a circle, about -1..1, loop-exact
    cyc = max(1.0, round(L / float(period)))
    a = (i / float(L)) * 2.0 * math.pi
    r = cyc / (2.0 * math.pi)
    v = hou.hmath.noise1d([math.cos(a) * r, math.sin(a) * r, seed * 0.0137 + 0.5])
    return max(-1.0, min(1.0, (v - 0.5) / 0.2))


def _pl_loop(n, frame):
    ev = n.evalParm
    st = int(round(ev("loop_start")))
    L = max(1, int(round(ev("loop_frames"))))
    i = int(math.floor(frame - st + 1e-6)) % L
    return st, L, i


def _pl_grid(n, L):
    """Beat grid in loop frames: (beat_len, div, offset, nslots, nbeats) or None when beat sync is off."""
    if _pl_parm(n, "lf_beat_sync") <= 0.5:
        return None
    bpm = _pl_parm(n, "lf_bpm")
    if bpm > 0.0:
        beats = bpm * L / float(hou.fps()) / 60.0
    else:
        beats = n.evalParm("lf_beats")
    beats = max(1.0, float(beats))
    div = max(1, int(round(_pl_parm(n, "lf_beat_div"))))
    off = int(round(_pl_parm(n, "lf_beat_offset")))
    beat_len = L / beats
    nbeats = int(math.ceil(L / beat_len - 1e-9))
    nslots = int(math.ceil(L / (beat_len / div) - 1e-9))
    return beat_len, div, off, nslots, nbeats


def _pl_slot(i, L, grid):
    """Grid slot of loop frame i: (slot index, frames since the slot started, slot length, is_downbeat)."""
    beat_len, div, off, nslots, nbeats = grid
    j = (i - off) % L
    slot_len = beat_len / div
    s = int(math.floor(j / slot_len + 1e-9))
    pos = j - s * slot_len
    return s, pos, slot_len, (s % div == 0)


def pearl_beat_frames(n):
    """Frames (absolute) on which a beat lands in one loop.  Handy to check the grid against the music."""
    st, L, _ = _pl_loop(n, st_frame(n))
    grid = _pl_grid(n, L)
    if grid is None:
        return []
    beat_len, div, off, nslots, nbeats = grid
    out = []
    for b in range(nbeats):
        out.append(st + (int(math.ceil(b * beat_len - 1e-9)) + off) % L)
    return sorted(out)


def st_frame(n):
    return int(round(n.evalParm("loop_start")))


def _pearl_light_levels_raw(n, frame):
    ev = n.evalParm
    if not ev("lf_enable"):
        return [1.0, 1.0, 1.0, 1.0, 1.0]
    st, L, fi = _pl_loop(n, frame)

    def loc(off):
        i = int(fi - off) % L
        return i, st + i

    def ch(name, f):
        return n.parm(name).evalAtFrame(f)

    seed = ev("lf_seed") * 1000.0
    thr = ev("lf_dark_thresh"); swell_amt = ev("lf_swell_amt"); casc = ev("lf_cascade")
    grid = _pl_grid(n, L)
    darklen = max(1.0, _pl_parm(n, "lf_beat_darklen"))
    offbeat = max(0.0, min(1.0, _pl_parm(n, "lf_beat_offbeat")))
    maxrun = max(1, int(round(_pl_parm(n, "lf_beat_maxrun"))))
    lv = [1.0, 1.0, 1.0, 1.0]; hv = [1.0, 1.0, 1.0, 1.0]; mins = [0.0] * 4
    hold = ch("lf_keyhold", loc(0)[1]) > 0.5
    for k, nm in enumerate(_PL_NAMES):
        mins[k] = ev("lf_min_" + nm)
        d = abs(int(round(ev("lf_off_" + nm))))
        a = max(0.0, min(1.0, ch("lf_activity", loc(d)[1]), ch("lf_activity", loc(0)[1]), ch("lf_activity", loc(-d)[1])))   # enters d late, leaves d early
        if a <= 1e-4:
            continue
        sd = seed + 101.0 + 37.0 * k
        prob = ev("lf_prob_" + nm)
        if grid is not None:
            # beat mode: every light sits on the same grid, each decides per slot with its own seed
            s, pos, slot_len, down = _pl_slot(loc(0)[0], L, grid)
            nslots = grid[3]
            hv[k] = _pl_h(sd, s)
            p = prob * a * (1.0 if down else offbeat)
            def dark_slot(c):
                # would slot c be dark (same rule as below, activity of the current frame as proxy)
                c = c % nslots
                return _pl_h(sd, c) < prob * a * (1.0 if (c % grid[1] == 0) else offbeat)
            ok = pos < darklen - 1e-9 and not all(dark_slot(s - q) for q in range(1, maxrun + 1))
            strobe_dark = ok and hv[k] < p and not (k == 0 and hold)
        else:
            # v3 step mode
            i = (loc(0)[0] + 17 * k) % L                                                            # own phase
            step = max(1, int(round(ev("lf_step_" + nm))))
            s = i // step
            hv[k] = _pl_h(sd, s)
            ok = (s % 3 != 1) if step <= 2 else ((s % 2 == 0) and (i % step) < 4)   # dark runs <= 4 frames
            if s == (L - 1) // step:
                ok = False                                                            # last step before the wrap stays lit
            strobe_dark = ok and hv[k] < prob * a and not (k == 0 and hold)
        lvl = 1.0
        if strobe_dark:
            lvl = 1.0 - a * (1.0 - mins[k])
        per = ev("lf_swell_" + nm)
        if per > 0.5 and swell_amt > 0.0 and not (k == 0 and hold):
            lvl *= 1.0 + swell_amt * a * _pl_swell((loc(0)[0] + 17 * k) % L, L, per, sd + 5.0)   # slow drift keeps its own phase per light
            if not strobe_dark:
                lvl = max(lvl, thr + 0.05)      # the slow swell moves the light but never makes a dip on its own
        lv[k] = max(0.8 * mins[k], min(1.4, lvl))
    # arbiter: key dark -> at most one dark dome; never more than lf_max_dark dark
    dark = [k for k in range(4) if lv[k] < thr]
    if 0 in dark:
        for k in sorted([k for k in dark if k > 0], key=lambda k: (hv[k], k))[1:]:
            lv[k] = max(lv[k], 1.0)
    dark = sorted([k for k in range(4) if lv[k] < thr], key=lambda k: (hv[k], k))
    for k in dark[int(ev("lf_max_dark")):]:
        lv[k] = 1.0
    # accents cascade across the rig: dome6 -1, key 0, dome7 +1, grid +2, water +1 (x lf_cascade frames)
    acc = {0: 0, 1: -1, 2: 1, 3: 2, 4: 1}
    A = {}
    hit0 = max(0.0, ch("lf_hit", loc(0)[1]))          # big hits land on the same frame for every light
    for k, o in acc.items():
        i, F = loc(int(round(o * casc)))
        A[k] = (hit0, max(0.0, ch("lf_ripple", F)), max(0.0, ch("lf_dipA", F)), max(0.0, ch("lf_dipB", F)))
    for k in (0, 1):
        if A[k][2] > 0.0:
            lv[k] = min(lv[k], 1.0 - A[k][2] * (1.0 - mins[k]))
    for k in (2, 3):
        if A[k][3] > 0.0:
            lv[k] = min(lv[k], 1.0 - A[k][3] * (1.0 - mins[k]))
    # never let the whole rig sag together: if key + all domes are under 0.9, the brightest one goes back to full
    if all(lv[k] < 0.9 for k in range(4)):
        kb = max(range(4), key=lambda k: (lv[k], -k))
        lv[kb] = 1.0
    for k in range(4):
        up = min(1.0, 2.0 * (A[k][0] + A[k][1]))
        if up > 0.0:
            lv[k] = lv[k] + (1.0 - lv[k]) * up if lv[k] < 1.0 else lv[k]
    # warm water: beat swell on its own offset, rises when the others dip, never dark
    dw = abs(int(round(ev("lf_off_water"))))
    iw = loc(0)[0]
    aw = max(0.0, min(1.0, ch("lf_activity", loc(dw)[1]), ch("lf_activity", loc(0)[1]), ch("lf_activity", loc(-dw)[1])))
    if grid is not None:
        beat_len, div, off = grid[0], grid[1], grid[2]
        p = math.exp(-6.0 * ((((iw - off) % L) / beat_len) % 1.0))
    else:
        p = math.exp(-6.0 * ((ev("lf_beats") * iw / float(L)) % 1.0))
    n_dark = sum(1 for k in (1, 2, 3) if lv[k] < thr)
    key_dark = 1.0 if lv[0] < thr else 0.0
    hw, rw, dAw, dBw = A[4]
    w = 1.0 - ev("lf_water_depth") * aw * (1.0 - p) + ev("lf_water_anti") * aw * (n_dark / 3.0) + 0.15 * aw * key_dark + 0.3 * dAw - 0.15 * dBw
    per = ev("lf_swell_water")
    if per > 0.5 and swell_amt > 0.0:
        w *= 1.0 + 0.5 * swell_amt * aw * _pl_swell(iw, L, per, seed + 977.0)
    w = max(ev("lf_water_min"), min(1.3, w))
    kf, df, wf, rk = ev("lf_key_flash"), ev("lf_dome_flash"), ev("lf_water_flash"), ev("lf_ripple_key")
    rd, rwg = ev("lf_ripple_dome"), ev("lf_ripple_water")
    return [lv[0] * (1.0 + kf * A[0][0] + rk * A[0][1]),
            lv[1] * (1.0 + df * A[1][0] + rd * A[1][1]),
            lv[2] * (1.0 + df * A[2][0] + rd * A[2][1]),
            lv[3] * (1.0 + 0.75 * df * A[3][0] + rd * A[3][1]),
            w * (1.0 + wf * hw + rwg * rw)]


def _pl_blackout(n, frame):
    # full-dark blink: the whole rig drops by fl_blackout_depth (0.85 -> lands on the 15 % floor), then back.
    # Beat mode: only on downbeats, lasting fl_blackout_step frames from the beat frame, at most
    # fl_blackout_maxrun beats in a row.  Never before Start Frame, never on the white hits / apex
    # ripple / key-hold hero moments.
    ev = n.evalParm
    amt = ev("fl_blackout")
    if amt <= 0.0 or not ev("lf_enable"):
        return 0.0
    st, L, i = _pl_loop(n, frame)
    F = st + i
    act = max(0.0, min(1.0, n.parm("lf_activity").evalAtFrame(F)))
    if act <= 1e-4:
        return 0.0
    if n.parm("lf_keyhold").evalAtFrame(F) > 0.5 or n.parm("lf_hit").evalAtFrame(F) > 0.0 or n.parm("lf_ripple").evalAtFrame(F) > 0.0:
        return 0.0
    seed = ev("lf_seed") * 1000.0 + 523.0
    p = amt * act
    run = max(1, int(round(ev("fl_blackout_maxrun"))))
    step = max(1.0, ev("fl_blackout_step"))
    depth = max(0.0, min(1.0, ev("fl_blackout_depth")))
    grid = _pl_grid(n, L)
    if grid is not None:
        s, pos, slot_len, down = _pl_slot(i, L, grid)
        if not down or pos >= step - 1e-9:
            return 0.0
        div, nbeats = grid[1], grid[4]
        b = s // div

        def raw(c):
            return _pl_h(seed, c % nbeats) < p
        if raw(b) and not all(raw(b - q) for q in range(1, run + 1)):
            return depth
        return 0.0
    # v3 step mode
    step = max(1, int(round(step)))
    nsteps = (L - 1) // step + 1
    s = i // step
    if s == nsteps - 1:
        return 0.0

    def raw3(c):
        return _pl_h(seed, c % nsteps) < p
    if raw3(s) and not all(raw3(s - q) for q in range(1, run + 1)):
        return depth
    return 0.0


def _pl_norm(n, frame):
    """The five levels at `frame` before the envelope: flicker mix, full-dark blink, floor.  1.0 = steady."""
    raw = _pearl_light_levels_raw(n, frame)
    ev = n.evalParm
    mix = max(0.0, min(1.0, ev("lm_flicker_mix")))          # 0 = steady light, 1 = full flicker
    bo = _pl_blackout(n, frame)
    floor = max(0.0, min(1.0, _pl_parm(n, "lf_floor")))
    out = []
    for v in raw:
        x = (1.0 + mix * (v - 1.0)) * (1.0 - bo)
        if x < floor:
            x = floor
        out.append(x)
    return out


def pearl_light_levels(n, frame):
    """Final multipliers for [key, dome6, dome7, grid, water]: envelope, per-light mix, master."""
    ev = n.evalParm
    master = max(0.0, ev("lm_master"))
    cur = _pl_norm(n, frame)
    att = max(0, int(round(_pl_parm(n, "lf_env_attack"))))
    rel = max(0, int(round(_pl_parm(n, "lf_env_release"))))
    if ev("lf_enable") and (att > 0 or rel > 0):
        # dips ramp in over `att` frames and out over `rel` frames: a loop-local tent over the neighbours.
        # The keyed white hits / apex ripple frames are left alone so a hero flash is never dimmed.
        st, L, i = _pl_loop(n, frame)
        F = st + i
        hitnow = n.parm("lf_hit").evalAtFrame(F) > 0.0 or n.parm("lf_ripple").evalAtFrame(F) > 0.0
        if not hitnow:
            env = [0.0] * 5
            for j in range(-att, rel + 1):
                if j == 0:
                    continue
                w = 1.0 - abs(j) / float((att if j < 0 else rel) + 1)
                lv = _pl_norm(n, st + ((i - j) % L))
                for k in range(5):
                    dip = (1.0 - lv[k]) * w
                    if dip > env[k]:
                        env[k] = dip
            cur = [min(v, 1.0 - env[k]) for k, v in enumerate(cur)]
    return [v * max(0.0, ev(p)) * master for v, p in zip(cur, _PL_MIX)]
'''


# ------------------------------------------------------------------------------------------------
def log(msg):
    print("[pearl v4] " + msg)


def fail(msg):
    raise RuntimeError("[pearl v4] " + msg)


def ctrl():
    n = hou.node(CTRL)
    if n is None:
        fail("%s not found: load untitled_water_realism_v001.hiplc first" % CTRL)
    for p in ("loop_start", "loop_frames", "lf_enable", "fl_blackout_depth", "lf_beats", "lm_master",
              "lm_flicker_mix", "close_amount", "lf_activity", "lf_hit", "lvl_key"):
        if n.parm(p) is None:
            fail("%s has no parm '%s': is this the right scene?" % (CTRL, p))
    return n


# ------------------------------------------------------------------------------------------------
def step_engine():
    """Install the v4 light engine as the scene's hou.session module."""
    cur = hou.sessionModuleSource() or ""
    if "v4, 2026-10-03" in cur and "def pearl_light_levels" in cur:
        log("engine: v4 already installed")
        return
    if "def pearl_light_levels" not in cur:
        log("engine: WARNING the loaded scene has no pearl_light_levels in hou.session (expected the v3 engine); installing v4 anyway")
    hou.setSessionModuleSource(ENGINE_SRC)
    # make sure it compiled: evaluate one level
    n = ctrl()
    try:
        v = hou.session.pearl_light_levels(n, float(n.evalParm("loop_start")))
    except Exception as e:   # noqa: BLE001
        fail("engine: hou.session did not evaluate: %r" % (e,))
    if len(v) != 5:
        fail("engine: pearl_light_levels returned %r" % (v,))
    log("engine: v4 installed (hou.session), test eval at loop start = %s" % (["%.3f" % x for x in v],))


# ------------------------------------------------------------------------------------------------
def _float(name, label, default, lo, hi, help_=""):
    return hou.FloatParmTemplate(name, label, 1, default_value=(default,), min=lo, max=hi,
                                 min_is_strict=False, max_is_strict=False, help=help_)


def _int(name, label, default, lo, hi, help_=""):
    return hou.IntParmTemplate(name, label, 1, default_value=(default,), min=lo, max=hi,
                               min_is_strict=False, max_is_strict=False, help=help_)


def _toggle(name, label, default, help_=""):
    return hou.ToggleParmTemplate(name, label, default_value=bool(default), help=help_)


NEW_FLICKER_PARMS = [   # inserted after fl_blackout_step on the "Light Flicker" tab, in this order
    _float("lf_floor", "Dark Floor", 0.15, 0.0, 1.0,
           "No main light goes below this share of its steady brightness. Client note: 15 %."),
    _int("lf_env_attack", "Dip Ramp In (frames)", 1, 0, 6,
         "Frames a dip takes to reach full depth (small ramp instead of a hard switch)."),
    _int("lf_env_release", "Dip Ramp Out (frames)", 2, 0, 8,
         "Frames a dip takes to come back up."),
    _toggle("lf_beat_sync", "Flicker On The Beat", 1,
            "Dips and full-dark blinks start on the beat grid. Off = the old free-running step flicker."),
    _float("lf_bpm", "Track BPM (0 = use Beats per Loop)", 0.0, 0.0, 200.0,
           "Tempo of the track. 0 uses 'Beats per Loop' (Advanced). For a seamless loop the loop must hold a whole number of beats: 540 f = 18 s, so 150 BPM = 45 beats."),
    _int("lf_beat_offset", "Beat Offset (frames)", 0, -12, 12,
         "Shift the whole beat grid to line the first downbeat up with the audio."),
    _int("lf_beat_div", "Dips per Beat", 2, 1, 4,
         "1 = only on the beat, 2 = eighth notes, 4 = sixteenths."),
    _float("lf_beat_darklen", "Dip Length (frames)", 2.0, 1.0, 6.0,
           "How many frames a dip stays at its darkest, counted from the beat frame."),
    _float("lf_beat_offbeat", "Off-beat Dip Chance", 0.5, 0.0, 1.0,
           "Dips between the beats happen this fraction as often as dips on the beat."),
    _int("lf_beat_maxrun", "Max Dips in a Row", 3, 1, 8,
         "A light never dips on more than this many grid slots in a row."),
]

NEW_TIMING_PARMS = [    # inserted after glow on the "Timing" tab
    _toggle("hold_open", "Hold Shell Open (loop variant)", 0,
            "On: the shell stays in its open pose for the whole loop, the pearl stays out, the glow window stays open, "
            "the story accents (slam flash, landing dips, apex ripple, key hold) are off and the beat flicker runs on every frame. "
            "The keyed story animation is kept on the '... (story keys)' parms and comes back when this is off."),
    _float("hold_open_amount", "Hold Open: Close Amount", 0.0, -0.1, 1.0,
           "Close Amount used while 'Hold Shell Open' is on. 0 = the Open pose, -0.069 = the apex overshoot of the story keys."),
]


def step_parms():
    """Add the v4 spare parms to the controller (idempotent)."""
    n = ctrl()
    ptg = n.parmTemplateGroup()
    changed = False

    def add_after(anchor, templates):
        nonlocal changed
        prev = anchor
        for t in templates:
            if ptg.find(t.name()) is None:
                ptg.insertAfter(prev, t)
                changed = True
            prev = t.name()

    if ptg.find("fl_blackout_step") is None or ptg.find("glow") is None:
        fail("parms: expected 'fl_blackout_step' and 'glow' on %s" % CTRL)
    add_after("fl_blackout_step", NEW_FLICKER_PARMS)
    add_after("glow", NEW_TIMING_PARMS)
    # one '<name>_anim' float next to every keyed story channel: it will hold the keyframes
    for name, _val, _why in HOLD_OVERRIDES:
        src_t = ptg.find(name)
        if src_t is None:
            fail("parms: keyed channel '%s' not found on %s" % (name, CTRL))
        anim = name + "_anim"
        if ptg.find(anim) is None:
            t = hou.FloatParmTemplate(anim, src_t.label().replace("(keyed)", "").strip() + " (story keys)", 1,
                                      default_value=(0.0,), min=-1.0, max=1.0, min_is_strict=False, max_is_strict=False,
                                      help="The keyed story animation of '%s'. '%s' reads it unless Hold Shell Open is on." % (name, name))
            ptg.insertAfter(name, t)
            changed = True
    # refresh the stale BPM note on Beats per Loop
    bt = ptg.find("lf_beats")
    if bt is not None and "350" in (bt.help() or ""):
        bt.setHelp("Beats in one loop. 45 beats / 540 f @ 30 fps = 150 BPM. Used when Track BPM is 0.")
        ptg.replace("lf_beats", bt)
        changed = True
    if changed:
        n.setParmTemplateGroup(ptg)
        log("parms: v4 spare parms added")
    else:
        log("parms: already present")
    for name in [t.name() for t in NEW_FLICKER_PARMS + NEW_TIMING_PARMS] + [nm + "_anim" for nm, _, _ in HOLD_OVERRIDES]:
        if n.parm(name) is None:
            fail("parms: '%s' missing after setParmTemplateGroup" % name)


# ------------------------------------------------------------------------------------------------
def step_values():
    n = ctrl()
    for name, val in V4_VALUES.items():
        p = n.parm(name)
        if p.keyframes():
            log("values: %s is keyed/expressed, leaving it (wanted %s)" % (name, val))
            continue
        if abs(p.eval() - val) > 1e-9:
            p.set(val)
            log("values: %s = %s" % (name, val))


# ------------------------------------------------------------------------------------------------
def _frames(n):
    st = int(round(n.evalParm("loop_start")))
    L = int(round(n.evalParm("loop_frames")))
    return list(range(st, st + L + 1))        # one extra frame: the loop wrap


def step_hold_open():
    """Move the keyed story channels to '<name>_anim' and put the hold-open switch expression on the originals."""
    n = ctrl()
    frames = _frames(n)
    for name, held_value, why in HOLD_OVERRIDES:
        p, pa = n.parm(name), n.parm(name + "_anim")
        expr = 'if(ch("hold_open"), %s, ch("%s_anim"))' % (held_value, name)
        try:
            cur_expr = p.expression()
        except hou.OperationFailed:
            cur_expr = None
        if cur_expr is not None and cur_expr.strip() == expr:
            log("hold-open: %s already switched" % name)
            continue
        keys = p.keyframes()
        if not keys:
            fail("hold-open: %s has no keyframes and is not switched yet; refusing to guess" % name)
        before = [p.evalAtFrame(f) for f in frames]
        pa.deleteAllKeyframes()
        pa.setKeyframes(keys)
        after = [pa.evalAtFrame(f) for f in frames]
        bad = [(f, a, b) for f, a, b in zip(frames, before, after) if abs(a - b) > 1e-6]
        if bad:
            pa.deleteAllKeyframes()
            fail("hold-open: copying the keys of %s to %s_anim changed the curve at frame %s (%s vs %s); nothing was altered" % (name, name, bad[0][0], bad[0][1], bad[0][2]))
        p.deleteAllKeyframes()
        p.setExpression(expr, language=hou.exprLanguage.Hscript)
        check = [p.evalAtFrame(f) for f in frames]
        bad = [(f, a, b) for f, a, b in zip(frames, before, check) if abs(a - b) > 1e-6]
        if bad:
            fail("hold-open: %s does not evaluate like before at frame %s (%s vs %s). Undo (Ctrl+Z) and report this." % (name, bad[0][0], bad[0][1], bad[0][2]))
        log("hold-open: %s -> %s_anim, switch expression set (%s)" % (name, name, why))
    # lf_activity is an expression, not keys: wrap it
    p = n.parm("lf_activity")
    try:
        cur = p.expression().strip()
    except hou.OperationFailed:
        cur = None
    if cur is None:
        fail("hold-open: lf_activity is expected to be an expression (fl_start / fl_end window)")
    if 'ch("hold_open")' not in cur:
        p.setExpression('if(ch("hold_open"), 1, %s)' % cur, language=hou.exprLanguage.Hscript)
        log("hold-open: lf_activity = 1 for every frame while held open")
    else:
        log("hold-open: lf_activity already switched")
    # the controller's own glow expression keys off 'glow' which now reads glow_anim: nothing to do.
    n.parm("hold_open").set(0)


# ------------------------------------------------------------------------------------------------
def step_rop():
    """Copy the FLICKER ROP to an OPEN_LOOP ROP that renders the hold-open variant of the loop."""
    out = hou.node(OUT)
    if out.node(OPEN_ROP) is not None:
        log("rop: %s already exists" % OPEN_ROP)
        return
    src = out.node(SRC_ROP)
    if src is None:
        log("rop: WARNING %s/%s not found, no hold-open ROP made (any ROP renders the variant with 'Hold Shell Open' and 'Flicker On' on)" % (OUT, SRC_ROP))
        return
    rop = hou.copyNodesTo((src,), out)[0]
    rop.setName(OPEN_ROP, unique_name=True)
    rop.setPosition(src.position() + hou.Vector2(3.0, 0.0))
    # same mechanism as the FLICKER ROP (pre-frame / post-render python), plus the hold-open switch
    pre = 'hou.parm("%s/lf_enable").set(1)\nhou.parm("%s/hold_open").set(1)' % (CTRL, CTRL)
    post = 'hou.parm("%s/lf_enable").set(0)\nhou.parm("%s/hold_open").set(0)' % (CTRL, CTRL)
    for toggle, lang, script, val in (("tpreframe", "lpreframe", "preframe", pre), ("tpostrender", "lpostrender", "postrender", post)):
        if rop.parm(script) is None:
            fail("rop: %s has no '%s' parm" % (rop.path(), script))
        rop.parm(script).set(val)
        if rop.parm(lang) is not None:
            rop.parm(lang).set("python")
        if rop.parm(toggle) is not None:
            rop.parm(toggle).set(1)
    pp = rop.parm("RS_outputFileNamePrefix")
    if pp is not None:
        v = pp.unexpandedString()
        nv = re.sub("flicker", "open_loop", v, flags=re.I)
        if nv == v:
            # no 'flicker' in the path: add a suffix before the frame number, keeping $HIPNAME intact ("${HIPNAME}_open_loop")
            v2 = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)(?=_)", r"${\1}", v)
            if ".$F" in v2:
                nv = re.sub(r"(\.\$F\d*)", r"_open_loop\1", v2, count=1)
            else:
                b, e = os.path.splitext(v2)
                nv = b + "_open_loop" + e
            nv = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)_open_loop", r"${\1}_open_loop", nv)
        pp.set(nv)
        log("rop: output %s" % nv)
    try:
        f1, f2 = rop.parmTuple("f").eval()[:2]
        rng = "%d-%d" % (f1, f2)
    except Exception:   # noqa: BLE001
        rng = "as FLICKER"
    rop.setComment("Hold-open loop: shell open, tree looping, beat flicker. Frames %s (follows the FLICKER ROP's range)." % rng)
    rop.setGenericFlag(hou.nodeFlag.DisplayComment, True)
    log("rop: %s/%s created (frames %s; pre-frame sets Flicker On + Hold Shell Open, post-render clears both)" % (OUT, OPEN_ROP, rng))


# ------------------------------------------------------------------------------------------------
def step_report():
    n = ctrl()
    st = int(round(n.evalParm("loop_start"))); L = int(round(n.evalParm("loop_frames")))
    beats = hou.session.pearl_beat_frames(n)
    log("beat grid: %d beats per loop, first beats at frames %s ..." % (len(beats), beats[:8]))
    log("set 'Track BPM' (or Advanced > Beats per Loop) on %s once the track is confirmed; %d frames = %.1f s" % (CTRL, L, L / hou.fps()))
    # a quick look at the result: minimum and maximum level over the loop with lf_enable on
    was = n.evalParm("lf_enable")
    n.parm("lf_enable").set(1)
    try:
        lo = [9.9] * 5; hi = [0.0] * 5
        for f in range(st, st + L):
            v = hou.session.pearl_light_levels(n, float(f))
            lo = [min(a, b) for a, b in zip(lo, v)]; hi = [max(a, b) for a, b in zip(hi, v)]
        master = n.evalParm("lm_master")
        log("levels over the loop (share of steady light): min %s max %s" % (
            ["%.2f" % (x / master) for x in lo], ["%.2f" % (x / master) for x in hi]))
    finally:
        n.parm("lf_enable").set(was)


def step_save():
    path = hou.hipFile.path()
    base, ext = os.path.splitext(path)
    if base.endswith("_v001"):
        new = base[:-5] + "_v002" + ext
    elif "_v004lights" in base:
        new = path
    else:
        new = base + "_v004lights" + ext
    hou.hipFile.save(file_name=new)
    log("saved %s" % new)
    return new


def main(argv=None):
    argv = list(argv or [])
    if argv and os.path.isfile(argv[0]):
        hou.hipFile.load(argv[0], suppress_save_prompt=True, ignore_load_warnings=True)
    step_engine()
    step_parms()
    step_values()
    step_hold_open()
    step_rop()
    step_report()
    return step_save()


if __name__ == "__main__" and not hou.isUIAvailable():
    main(sys.argv[1:])          # hython apply_v004.py <scene.hiplc>
else:
    main()                      # exec()'d in the Houdini Python shell / Source Editor with the scene loaded
