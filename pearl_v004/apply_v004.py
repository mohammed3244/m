# -*- coding: utf-8 -*-
"""
PEARL_ANIM v4: apply the client notes of 2026-10-02 to untitled_water_realism_v001.hiplc

    1. main lights dim 100 % -> 15 % (not to black) with a small ramp in / ramp out
    2. the tree lights are untouched
    3. the flicker sits on the beat grid (150 BPM = 45 beats per 540-frame loop by default; set the
       real BPM on /obj/PEARL_ANIM "Track BPM" once the track is known)
    4. a "hold open" loop variant: shell stays in the open pose, the tree cache ping-pongs through its
       fully grown frames so the tree keeps moving, lights keep flickering; rendered by the new
       /out/Redshift_ROP_OPEN_LOOP (full quality) and /out/Redshift_ROP_OPEN_LOOP_FAST (preview)

Run it INSIDE Houdini 21 with the v001 scene loaded (Windows > Python Shell):

    exec(open(r"C:\\path\\to\\apply_v004.py").read())

or from a terminal:

    hython apply_v004.py "C:\\Users\\gtava\\OneDrive\\Desktop\\SARA\\2\\untitled_water_realism_v001.hiplc"

It never overwrites the loaded file: it saves a copy next to it as *_v002.hiplc (or *_v004lights.hiplc
when the name has no _v001) and refuses to overwrite an existing file.  Every step is idempotent, so
running it twice, or running it on a v002 made by make_v002.py, changes nothing.
Turn "Hold Shell Open" off and the scene evaluates exactly as before (the script verifies this on
every frame before it swaps the keyframes over).

The constants below are the single description of the change; make_v002.py (offline builder) imports
this file for them, which is why `import hou` is guarded.
"""
import os
import re
import sys

try:
    import hou
except ImportError:          # offline: make_v002.py / tests import this module for the spec only
    hou = None

CTRL = "/obj/PEARL_ANIM"
OUT = "/out"
TREE_TIMESHIFT = "/obj/geo1/timeshift2"
TREE_CTRL = "/obj/TREE_BASE_CTRL"

# ---------------------------------------------------------------------------------------------------
# the spec
# ---------------------------------------------------------------------------------------------------
# new spare parms: (name, label, kind, default, min, max, help); kind = float | int | toggle
PARMS_FLICKER = [   # Light Flicker tab, inserted after fl_blackout_step in this order
    ("lf_floor", "Dark Floor", "float", 0.15, 0.0, 1.0,
     "No main light goes below this share of its steady brightness. Client note: 15 %."),
    ("lf_env_attack", "Dip Ramp In (frames)", "int", 1, 0, 6,
     "Frames a dip takes to reach full depth (small ramp instead of a hard switch)."),
    ("lf_env_release", "Dip Ramp Out (frames)", "int", 2, 0, 8,
     "Frames a dip takes to come back up."),
    ("lf_beat_sync", "Flicker On The Beat", "toggle", 1, None, None,
     "Dips and full-dark blinks start on the beat grid. Off = the old free-running step flicker (only then do Speed and the per-light Step parms act)."),
    ("lf_bpm", "Track BPM (0 = use Beats per Loop)", "float", 0.0, 0.0, 200.0,
     "Tempo of the track. 0 uses 'Beats per Loop' (Advanced). The loop is seamless when it holds a whole number of beats: at 540 f = 18 s that is any multiple of 3.33 BPM (90, 100, 110, 120, 130, 140, 150, 160, 170, 180). Beats that do not fall on whole frames reach full depth on the first frame at or after the beat."),
    ("lf_beat_offset", "Beat Offset (frames)", "int", 0, -12, 12,
     "Shift the whole beat grid to line the first downbeat up with the audio."),
    ("lf_beat_div", "Dips per Beat", "int", 2, 1, 4,
     "1 = only on the beat, 2 = eighth notes, 4 = sixteenths."),
    ("lf_beat_darklen", "Dip Length (frames)", "float", 2.0, 1.0, 6.0,
     "How many frames a dip stays at its darkest, counted from the beat frame."),
    ("lf_beat_offbeat", "Off-beat Dip Chance", "float", 0.5, 0.0, 1.0,
     "Dips between the beats happen this fraction as often as dips on the beat."),
    ("lf_beat_maxrun", "Max Dips in a Row", "int", 3, 1, 8,
     "A light never dips on more than this many grid slots in a row."),
]
PARMS_TIMING = [    # Timing tab, inserted after glow in this order
    ("hold_open", "Hold Shell Open (loop variant)", "toggle", 0, None, None,
     "On: the shell stays in its open pose for the whole loop, the pearl stays out, the glow window stays open, "
     "the story accents (slam flash, landing dips, apex ripple, key hold) are off, the beat flicker runs on every frame, "
     "the tree cache ping-pongs through its fully grown frames and the tree glow window covers the whole loop. "
     "The keyed story animation is kept on the '... (story keys)' parms and comes back when this is off."),
    ("hold_open_amount", "Hold Open: Close Amount", "float", 0.0, -0.1, 1.0,
     "Close Amount used while 'Hold Shell Open' is on. 0 = the Open pose, -0.069 = the apex over-open of the story keys."),
    ("hold_open_breath", "Hold Open: Shell Breath", "float", 0.0, 0.0, 1.0,
     "A slow, loop-exact breath from the held pose toward the apex over-open (-0.069) and back, once per loop. 0 = perfectly still."),
    ("hold_open_pearl", "Hold Open: Keep Pearl Water Events", "toggle", 0, None, None,
     "On: the keyed pearl rise and descent keep driving the water rings while the shell is held open. "
     "Off: the pearl stays out, and the water shows only its swell and the pearl bob ripple."),
    ("hold_open_tree_from", "Hold Open: Tree Cache Frame", "int", 124, 1, 600,
     "First fully grown frame of the tree cache. While held open the tree cache plays from here forward for half the loop and back again "
     "(a seamless ping-pong), so the tree keeps moving without growing in or out. The story keys grow the tree in over frames 1-124 and out over 455-541."),
]

# keyed story channels that the hold-open toggle switches: (name, switch expression on the original parm)
# the keyframes move to '<name>_anim' ("... (story keys)")
HOLD_SWITCH = [
    ("close_amount", 'if(ch("hold_open"), ch("hold_open_amount") - ch("hold_open_breath") * 0.068735732 * 0.5 * (1 - cos(360 * ($F - ch("loop_start")) / ch("loop_frames"))), ch("close_amount_anim"))'),
    ("pearl_in",     'if(ch("hold_open") * (1 - ch("hold_open_pearl")), 0, ch("pearl_in_anim"))'),
    ("pearl_out",    'if(ch("hold_open") * (1 - ch("hold_open_pearl")), 1, ch("pearl_out_anim"))'),
    ("glow",         'if(ch("hold_open"), 1, ch("glow_anim"))'),
    ("lf_hit",       'if(ch("hold_open"), 0, ch("lf_hit_anim"))'),
    ("lf_keyhold",   'if(ch("hold_open"), 0, ch("lf_keyhold_anim"))'),
    ("lf_dipA",      'if(ch("hold_open"), 0, ch("lf_dipA_anim"))'),
    ("lf_dipB",      'if(ch("hold_open"), 0, ch("lf_dipB_anim"))'),
    ("lf_ripple",    'if(ch("hold_open"), 0, ch("lf_ripple_anim"))'),
]
LF_ACTIVITY_OLD = 'if($F >= ch("fl_start") && $F <= ch("fl_end"), 1, 0)'
LF_ACTIVITY_NEW = 'if(ch("hold_open"), 1, %s)' % LF_ACTIVITY_OLD

# tree: the baked tree cache (filecache, frames 1-600) grows in over 1-124 and out over 455-541.  While held
# open, /obj/geo1/timeshift2 (currently bypassed, frame = 1) plays the fully grown frames as a ping-pong.
TREE_TIMESHIFT_EXPR = ('if(ch("/obj/PEARL_ANIM/hold_open"), ch("/obj/PEARL_ANIM/hold_open_tree_from") + '
                       '(ch("/obj/PEARL_ANIM/loop_frames") / 2 - abs((($F - ch("/obj/PEARL_ANIM/loop_start")) % ch("/obj/PEARL_ANIM/loop_frames")) '
                       '- ch("/obj/PEARL_ANIM/loop_frames") / 2)), $F)')
# tree glow envelope (TREE_BASE_CTRL Tree Glow tab): smooth(start, start + fade) * (1 - smooth(end - fade, end)) on the raw frame;
# while held open it must be 1 on every frame.  (parm, value while held); the story value is kept in the expression
TREE_GLOW_WINDOW = [("glow_start", -100.0), ("glow_end", 1000.0)]


def _num(v):
    return "%g" % float(v)


def tree_glow_expr(current_value, held_value):
    return 'if(ch("/obj/PEARL_ANIM/hold_open"), %s, %s)' % (_num(held_value), _num(current_value))


# ROPs: (source node, new node, output tag in the source path, output tag of the new one)
ROPS = [
    ("Redshift_ROP_18S_GLOW", "Redshift_ROP_OPEN_LOOP", "18s_glow", "open_loop"),
    ("Redshift_ROP_GLOW_FAST", "Redshift_ROP_OPEN_LOOP_FAST", "glow_fast", "open_loop_fast"),
]
ROP_PRE = 'hou.parm("%s/lf_enable").set(1)\nhou.parm("%s/hold_open").set(1)' % (CTRL, CTRL)
ROP_POST = 'hou.parm("%s/lf_enable").set(0)\nhou.parm("%s/hold_open").set(0)' % (CTRL, CTRL)
ROP_COMMENT = "Hold-open loop: shell open, tree ping-pong, beat flicker. Pre-frame turns Flicker On + Hold Shell Open on, post-render turns both off."


def rop_output_path(path, old_tag, new_tag):
    nv = re.sub(re.escape(old_tag), new_tag, path, flags=re.I)
    nv = re.sub(r"/render\d+_", "/render_", nv)
    if nv == path:
        v2 = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)(?=_)", r"${\1}", path)
        if ".$F" in v2:
            nv = re.sub(r"(\.\$F\d*)", r"_" + new_tag + r"\1", v2, count=1)
        else:
            b, e = os.path.splitext(v2)
            nv = b + "_" + new_tag + e
        nv = re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)_" + new_tag, r"${\1}_" + new_tag, nv)
    return nv


# plain values on the controller: (v001 value, v4 value).  Only migrated while still at the v001 value, so a
# re-run never undoes the artist's tuning.
V4_VALUES = {
    "fl_blackout_depth": (1.0, 0.85),   # full-dark blink lands on the 15 % floor instead of black
    "lf_beats": (29.0, 45.0),           # 45 beats / 540 f @ 30 fps = 150 BPM (the old note said 149 BPM for the 350 f loop)
}

# roots: /obj/tree_roots grows and retracts the roots with TREE_BASE_CTRL/growth (a locked link to the keyed
# tree growth), so while the tree cache is held fully grown the roots must be held at full growth too
TREE_GROWTH_OLD = 'ch("/obj/geo1/simple_grow1/growth")'
TREE_GROWTH_NEW = 'if(ch("/obj/PEARL_ANIM/hold_open"), 1, %s)' % TREE_GROWTH_OLD

# every existing ROP whose pre-frame script switches Flicker On also forces Hold Shell Open off, so a cancelled
# hold-open render (whose post-render script never ran) cannot leak into a story render
STORY_ROP_PREFIX = 'hou.parm("%s/hold_open").set(0)\n' % CTRL
LF_BEATS_HELP_OLD_MARK = "350"
LF_BEATS_HELP = "Beats in one loop. 45 beats / 540 f @ 30 fps = 150 BPM. Used when Track BPM is 0."

ENGINE_MARK = "v4, 2026-10-03"
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
    # count only the beats / slots whose first integer frame lies inside the loop (a beat that would start
    # exactly on frame L never happens, it is frame 0 of the next loop)
    nbeats = int(math.floor((L - 1) / beat_len + 1e-9)) + 1
    nslots = int(math.floor((L - 1) / (beat_len / div) + 1e-9)) + 1
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


def _pearl_light_levels_raw(n, frame, grid=None):
    ev = n.evalParm
    if not ev("lf_enable"):
        return [1.0, 1.0, 1.0, 1.0, 1.0]
    st, L, fi = _pl_loop(n, frame)
    if grid is None:
        grid = _pl_grid(n, L)

    def loc(off):
        i = int(fi - off) % L
        return i, st + i

    def ch(name, f):
        return n.parm(name).evalAtFrame(f)

    seed = ev("lf_seed") * 1000.0
    thr = ev("lf_dark_thresh"); swell_amt = ev("lf_swell_amt"); casc = ev("lf_cascade")
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


def _pl_accent(n, F):
    """True on a frame that carries one of the keyed story accents (hits, apex ripple, dip groups)."""
    for name in ("lf_hit", "lf_ripple", "lf_dipA", "lf_dipB"):
        if n.parm(name).evalAtFrame(F) > 0.0:
            return True
    return False


def _pl_blackout(n, frame, grid=None):
    # full-dark blink: the whole rig drops by fl_blackout_depth (0.85 -> lands on the 15 % floor), then back.
    # Beat mode: only on downbeats, lasting fl_blackout_step frames from the beat frame, at most
    # fl_blackout_maxrun beats in a row.  Never before Start Frame, never on or next to the keyed
    # story accents (white hits, apex ripple, dip groups) and never in a key-hold hero moment.
    ev = n.evalParm
    amt = ev("fl_blackout")
    if amt <= 0.0 or not ev("lf_enable"):
        return 0.0
    st, L, i = _pl_loop(n, frame)
    F = st + i
    act = max(0.0, min(1.0, n.parm("lf_activity").evalAtFrame(F)))
    if act <= 1e-4:
        return 0.0
    if n.parm("lf_keyhold").evalAtFrame(F) > 0.5:
        return 0.0
    if grid is None:
        grid = _pl_grid(n, L)
    if grid is not None:
        for d in (-1, 0, 1):            # beat mode: keep the frames around the keyed accents clean
            if _pl_accent(n, st + ((i + d) % L)):
                return 0.0
    elif n.parm("lf_hit").evalAtFrame(F) > 0.0 or n.parm("lf_ripple").evalAtFrame(F) > 0.0:
        return 0.0                      # v3 rule
    seed = ev("lf_seed") * 1000.0 + 523.0
    p = amt * act
    run = max(1, int(round(ev("fl_blackout_maxrun"))))
    step = max(1.0, ev("fl_blackout_step"))
    depth = max(0.0, min(1.0, ev("fl_blackout_depth")))
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


def _pl_norm(n, frame, grid=None):
    """The five levels at `frame` before the envelope: flicker mix, full-dark blink, floor.  1.0 = steady."""
    ev = n.evalParm
    if grid is None:
        grid = _pl_grid(n, _pl_loop(n, frame)[1])
    raw = _pearl_light_levels_raw(n, frame, grid)
    mix = max(0.0, min(1.0, ev("lm_flicker_mix")))          # 0 = steady light, 1 = full flicker
    bo = _pl_blackout(n, frame, grid)
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
    st, L, i = _pl_loop(n, frame)
    grid = _pl_grid(n, L) if ev("lf_enable") else None
    cur = _pl_norm(n, frame, grid)
    att = max(0, int(round(_pl_parm(n, "lf_env_attack"))))
    rel = max(0, int(round(_pl_parm(n, "lf_env_release"))))
    if ev("lf_enable") and (att > 0 or rel > 0):
        # dips ramp in over `att` frames and out over `rel` frames: a loop-local tent over the neighbours.
        # The keyed white hits / apex ripple frames are left alone so a hero flash is never dimmed, and the
        # key light is left alone while Key Hold is on.
        F = st + i
        hitnow = n.parm("lf_hit").evalAtFrame(F) > 0.0 or n.parm("lf_ripple").evalAtFrame(F) > 0.0
        if not hitnow:
            hold = n.parm("lf_keyhold").evalAtFrame(F) > 0.5
            env = [0.0] * 5
            for j in range(-att, rel + 1):
                if j == 0:
                    continue
                w = 1.0 - abs(j) / float((att if j < 0 else rel) + 1)
                lv = _pl_norm(n, st + ((i - j) % L), grid)
                for k in range(5):
                    dip = (1.0 - lv[k]) * w
                    if dip > env[k]:
                        env[k] = dip
            cur = [v if (k == 0 and hold) else min(v, 1.0 - env[k]) for k, v in enumerate(cur)]
    return [v * max(0.0, ev(p)) * master for v, p in zip(cur, _PL_MIX)]
'''


def anim_name(name):
    return name + "_anim"


def story_label(label):
    """Label of the original parm once it is driven by the switch expression: 'Close Amount (keyed)' -> 'Close Amount'."""
    return re.sub(r"\s*\(keyed[^)]*\)", "", label).strip()


def anim_label(label):
    return story_label(label) + " (story keys)"


def anim_help(name):
    return "The keyed story animation of '%s'. '%s' reads it unless Hold Shell Open is on." % (name, name)


# ---------------------------------------------------------------------------------------------------
# Houdini side
# ---------------------------------------------------------------------------------------------------
_CHANGES = []


def log(msg):
    print("[pearl v4] " + msg)


def changed(msg):
    _CHANGES.append(msg)
    log(msg)


def fail(msg):
    raise RuntimeError("[pearl v4] " + msg)


def ctrl():
    n = hou.node(CTRL)
    if n is None:
        fail("%s not found: load untitled_water_realism_v001.hiplc first" % CTRL)
    for p in ("loop_start", "loop_frames", "lf_enable", "fl_blackout_depth", "lf_beats", "lm_master",
              "lm_flicker_mix", "close_amount", "lf_activity", "lf_hit", "lvl_key", "fl_blackout_step", "glow"):
        if n.parm(p) is None:
            fail("%s has no parm '%s': is this the right scene?" % (CTRL, p))
    return n


def _expression_or_none(p):
    try:
        return p.expression()
    except hou.OperationFailed:
        return None


def _is_switched(p, name):
    e = (_expression_or_none(p) or "")
    return 'ch("hold_open")' in e and anim_name(name) in e


def _is_story_keyed(p):
    keys = p.keyframes()
    return len(keys) >= 2 and all(k.expression().strip() in ("bezier()", "linear()", "constant()", "cubic()", "ease()", "easein()", "easeout()", "spline()", "qlinear()", "quintic()", "matchin()", "matchout()") for k in keys)


def save_target():
    path = hou.hipFile.path()
    base, ext = os.path.splitext(path)
    if base.endswith("_v001"):
        return base[:-5] + "_v002" + ext
    if base.endswith("_v002") or "_v004lights" in base:
        return path
    return base + "_v004lights" + ext


def preflight():
    """Read-only checks of everything the steps rely on; nothing is touched before this passes."""
    n = ctrl()
    if hou.hipFile.hasUnsavedChanges():
        fail("the scene has unsaved changes; save (or revert) first, so a failed run can be undone by re-opening the file")
    ptg = n.parmTemplateGroup()
    for a in ("fl_blackout_step", "glow"):
        if ptg.find(a) is None:
            fail("preflight: parm '%s' not found on %s" % (a, CTRL))
    for name, _expr in HOLD_SWITCH:
        p = n.parm(name)
        if p is None:
            fail("preflight: story channel '%s' not found on %s" % (name, CTRL))
        pa = n.parm(anim_name(name))
        if _is_switched(p, name):
            if pa is None or not pa.keyframes():
                fail("preflight: %s is already switched but %s holds no keys; the story animation is missing" % (name, anim_name(name)))
        elif not _is_story_keyed(p):
            fail("preflight: %s is neither keyed story animation nor switched (keys: %d); refusing to guess" % (name, len(p.keyframes())))
        elif pa is not None and pa.keyframes():
            fail("preflight: %s already holds keys while %s is still keyed; sort that out by hand" % (anim_name(name), name))
    cur = (_expression_or_none(n.parm("lf_activity")) or "").strip()
    if not cur:
        fail("preflight: lf_activity is expected to be an expression (fl_start / fl_end window)")
    for src_name, new_name, _o, _n in ROPS:
        src = hou.node(OUT + "/" + src_name)
        if src is None:
            log("preflight: WARNING %s/%s not found; %s will not be made" % (OUT, src_name, new_name))
            continue
        for pn in ("preframe", "postrender", "lpreframe", "lpostrender", "RS_outputFileNamePrefix"):
            if src.parm(pn) is None:
                fail("preflight: %s/%s has no '%s' parm" % (OUT, src_name, pn))
    for path in (TREE_TIMESHIFT, TREE_CTRL):
        if hou.node(path) is None:
            log("preflight: WARNING %s not found; the tree part of the hold-open variant will be skipped" % path)
    target = save_target()
    if target != hou.hipFile.path() and os.path.exists(target):
        fail("preflight: %s already exists; move it away first (nothing was changed)" % target)
    log("preflight ok: %s -> %s" % (hou.hipFile.path(), target))


def step_engine():
    """Install the v4 light engine as the scene's hou.session module."""
    cur = hou.sessionModuleSource() or ""
    if ENGINE_MARK in cur and "def pearl_light_levels" in cur:
        log("engine: v4 already installed")
        return
    if "def pearl_light_levels" not in cur:
        log("engine: WARNING the loaded scene has no pearl_light_levels in hou.session (expected the v3 engine); installing v4 anyway")
    hou.setSessionModuleSource(ENGINE_SRC)
    n = ctrl()
    try:
        v = hou.session.pearl_light_levels(n, float(n.evalParm("loop_start")))
    except Exception as e:   # noqa: BLE001
        fail("engine: hou.session did not evaluate: %r" % (e,))
    if len(v) != 5:
        fail("engine: pearl_light_levels returned %r" % (v,))
    changed("engine: v4 installed (hou.session), test eval at loop start = %s" % (["%.3f" % x for x in v],))


def _template(spec):
    name, label, kind, default, lo, hi, help_ = spec
    if kind == "float":
        return hou.FloatParmTemplate(name, label, 1, default_value=(float(default),), min=float(lo), max=float(hi),
                                     min_is_strict=False, max_is_strict=False, help=help_)
    if kind == "int":
        return hou.IntParmTemplate(name, label, 1, default_value=(int(default),), min=int(lo), max=int(hi),
                                   min_is_strict=False, max_is_strict=False, help=help_)
    if kind == "toggle":
        return hou.ToggleParmTemplate(name, label, default_value=bool(default), help=help_)
    fail("unknown parm kind %r" % kind)


def step_parms():
    """Add the v4 spare parms to the controller (idempotent)."""
    n = ctrl()
    ptg = n.parmTemplateGroup()
    dirty = [False]

    def add_after(anchor, specs):
        prev = anchor
        for spec in specs:
            if ptg.find(spec[0]) is None:
                ptg.insertAfter(ptg.find(prev), _template(spec))
                dirty[0] = True
            prev = spec[0]

    add_after("fl_blackout_step", PARMS_FLICKER)
    add_after("glow", PARMS_TIMING)
    for name, _expr in HOLD_SWITCH:
        src_t = ptg.find(name)
        if src_t is None:
            fail("parms: keyed channel '%s' not found on %s" % (name, CTRL))
        if "(keyed" in src_t.label():
            src_t.setLabel(story_label(src_t.label()))
            ptg.replace(name, src_t)
            dirty[0] = True
        if ptg.find(anim_name(name)) is None:
            t = hou.FloatParmTemplate(anim_name(name), anim_label(src_t.label()), 1, default_value=(0.0,), min=-1.0, max=1.0,
                                      min_is_strict=False, max_is_strict=False, help=anim_help(name))
            ptg.insertAfter(name, t)
            dirty[0] = True
    bt = ptg.find("lf_beats")
    if bt is not None and LF_BEATS_HELP_OLD_MARK in (bt.help() or ""):
        bt.setHelp(LF_BEATS_HELP)
        ptg.replace("lf_beats", bt)
        dirty[0] = True
    if dirty[0]:
        n.setParmTemplateGroup(ptg)
        changed("parms: v4 spare parms added / labels updated")
    else:
        log("parms: already present")
    for name in [s[0] for s in PARMS_FLICKER + PARMS_TIMING] + [anim_name(nm) for nm, _ in HOLD_SWITCH]:
        if n.parm(name) is None:
            fail("parms: '%s' missing after setParmTemplateGroup" % name)


def step_values():
    n = ctrl()
    for name, (old, new) in V4_VALUES.items():
        p = n.parm(name)
        if p.keyframes():
            log("values: %s is keyed/expressed, leaving it (wanted %s)" % (name, new))
            continue
        cur = p.eval()
        if abs(cur - new) < 1e-9:
            log("values: %s already %s" % (name, new))
        elif abs(cur - old) < 1e-9:
            p.set(new)
            changed("values: %s %s -> %s" % (name, old, new))
        else:
            log("values: %s is %s (tuned by hand, not the v001 value %s); left as is, v4 wants %s" % (name, cur, old, new))


def _frames(n):
    st = int(round(n.evalParm("loop_start")))
    L = int(round(n.evalParm("loop_frames")))
    return list(range(st, st + L + 1))        # one extra frame: the loop wrap


def step_hold_open():
    """Move the keyed story channels to '<name>_anim' and put the hold-open switch expression on the originals."""
    n = ctrl()
    frames = _frames(n)
    hold_was = n.evalParm("hold_open")
    n.parm("hold_open").set(0)
    try:
        for name, expr in HOLD_SWITCH:
            p, pa = n.parm(name), n.parm(anim_name(name))
            if _is_switched(p, name):
                log("hold-open: %s already switched" % name)
                continue
            if not _is_story_keyed(p):
                fail("hold-open: %s is not keyed story animation; refusing to guess" % name)
            if pa.keyframes():
                fail("hold-open: %s already holds keys; refusing to overwrite them" % anim_name(name))
            keys = p.keyframes()
            before = [p.evalAtFrame(f) for f in frames]
            pa.setKeyframes(keys)
            after = [pa.evalAtFrame(f) for f in frames]
            bad = [(f, a, b) for f, a, b in zip(frames, before, after) if abs(a - b) > 1e-6]
            if bad:
                pa.deleteAllKeyframes()
                fail("hold-open: copying the keys of %s to %s changed the curve at frame %s (%s vs %s); the copy was removed, %s is untouched" % (name, anim_name(name), bad[0][0], bad[0][1], bad[0][2], name))
            try:
                pa.setAutoscope(True)
            except Exception:   # noqa: BLE001
                pass
            p.deleteAllKeyframes()
            p.setExpression(expr, language=hou.exprLanguage.Hscript)
            check = [p.evalAtFrame(f) for f in frames]
            bad = [(f, a, b) for f, a, b in zip(frames, before, check) if abs(a - b) > 1e-6]
            if bad:
                fail("hold-open: %s does not evaluate like before at frame %s (%s vs %s)" % (name, bad[0][0], bad[0][1], bad[0][2]))
            changed("hold-open: %s -> %s, switch expression set" % (name, anim_name(name)))
        p = n.parm("lf_activity")
        cur = (_expression_or_none(p) or "").strip()
        if cur == LF_ACTIVITY_NEW or 'ch("hold_open")' in cur:
            log("hold-open: lf_activity already switched")
        elif cur == LF_ACTIVITY_OLD:
            p.setExpression(LF_ACTIVITY_NEW, language=hou.exprLanguage.Hscript)
            changed("hold-open: lf_activity = 1 on every frame while held open")
        elif cur:
            p.setExpression('if(ch("hold_open"), 1, %s)' % cur, language=hou.exprLanguage.Hscript)
            changed("hold-open: lf_activity wrapped (expression differed from the v001 one: %s)" % cur)
        else:
            fail("hold-open: lf_activity is expected to be an expression (fl_start / fl_end window), found %r" % cur)
    finally:
        n.parm("hold_open").set(hold_was)


def _set_expr_locked_ok(p, expr):
    was_locked = p.isLocked()
    if was_locked:
        p.lock(False)
    try:
        p.deleteAllKeyframes()
        p.setExpression(expr, language=hou.exprLanguage.Hscript)
    finally:
        if was_locked:
            p.lock(True)


def step_tree():
    """Tree cache ping-pong, roots held grown and full glow window while the shell is held open."""
    n = ctrl()
    frames = _frames(n)
    st, L = frames[0], len(frames) - 1
    hold_was = n.evalParm("hold_open")
    ts = hou.node(TREE_TIMESHIFT)
    if ts is None:
        log("tree: WARNING %s not found; the tree will still grow in and out while held open" % TREE_TIMESHIFT)
    else:
        p = ts.parm("frame")
        if p is None:
            fail("tree: %s has no 'frame' parm (expected a Time Shift SOP)" % TREE_TIMESHIFT)
        cur = (_expression_or_none(p) or "").strip()
        if cur != TREE_TIMESHIFT_EXPR:
            if "hold_open" in cur:
                fail("tree: %s/frame already has a different hold_open expression: %s" % (TREE_TIMESHIFT, cur))
            _set_expr_locked_ok(p, TREE_TIMESHIFT_EXPR)
            changed("tree: %s/frame = ping-pong expression" % TREE_TIMESHIFT)
        if ts.isBypassed():
            ts.bypass(False)
            changed("tree: %s un-bypassed" % TREE_TIMESHIFT)
        if ts.parm("method") is not None and ts.parm("method").evalAsString() != "byframe":
            ts.parm("method").set("byframe")
            changed("tree: %s method = by frame" % TREE_TIMESHIFT)
        if ts.parm("integerframe") is not None and not ts.parm("integerframe").eval():
            ts.parm("integerframe").set(1)
            changed("tree: %s integer frame on" % TREE_TIMESHIFT)
        # verify: pass-through when off, seamless ping-pong inside the grown window when on
        try:
            n.parm("hold_open").set(0)
            bad = [f for f in frames if abs(p.evalAtFrame(f) - f) > 1e-6]
            if bad:
                fail("tree: with Hold Shell Open off, %s/frame is not the current frame at frame %s" % (TREE_TIMESHIFT, bad[0]))
            n.parm("hold_open").set(1)
            a = n.evalParm("hold_open_tree_from")
            vals = [p.evalAtFrame(f) for f in frames]
        finally:
            n.parm("hold_open").set(hold_was)
        if abs(vals[0] - a) > 1e-6 or abs(vals[-1] - a) > 1e-6 or abs(vals[L // 2] - (a + L / 2.0)) > 1e-6 or min(vals) < a - 1e-6 or max(vals) > a + L / 2.0 + 1e-6:
            fail("tree: ping-pong expression evaluates wrongly (first %s, mid %s, last %s, min %s, max %s)" % (vals[0], vals[L // 2], vals[-1], min(vals), max(vals)))
        log("tree: held open the cache plays frames %g..%g and back over frames %d-%d" % (a, a + L / 2.0, st, st + L - 1))
    tc = hou.node(TREE_CTRL)
    if tc is None:
        log("tree: WARNING %s not found; roots and tree glow window keep their story behaviour" % TREE_CTRL)
        return
    g = tc.parm("growth")
    if g is None:
        log("tree: WARNING %s/growth not found" % TREE_CTRL)
    else:
        cur = (_expression_or_none(g) or "").strip()
        if cur == TREE_GROWTH_OLD:
            _set_expr_locked_ok(g, TREE_GROWTH_NEW)
            changed("tree: %s/growth = 1 while held open (roots stay fully grown)" % TREE_CTRL)
        elif "hold_open" in cur:
            log("tree: %s/growth already switched" % TREE_CTRL)
        else:
            log("tree: WARNING %s/growth is %r, not the expected link to the tree growth; left alone (roots will follow it)" % (TREE_CTRL, cur))
    for name, held in TREE_GLOW_WINDOW:
        p = tc.parm(name)
        if p is None:
            log("tree: WARNING %s/%s not found" % (TREE_CTRL, name))
            continue
        cur = (_expression_or_none(p) or "").strip()
        if "hold_open" in cur:
            continue
        if p.keyframes():
            fail("tree: %s/%s is animated; expected a plain value" % (TREE_CTRL, name))
        _set_expr_locked_ok(p, tree_glow_expr(p.eval(), held))
        changed("tree: %s/%s = %s while held open (story value kept otherwise)" % (TREE_CTRL, name, _num(held)))


def step_rops():
    """Copy the full-quality and the fast glow ROPs to hold-open ROPs; story ROPs force Hold Shell Open off."""
    out = hou.node(OUT)
    for src_name, new_name, old_tag, new_tag in ROPS:
        if out.node(new_name) is not None:
            log("rop: %s already exists" % new_name)
            continue
        src = out.node(src_name)
        if src is None:
            log("rop: WARNING %s/%s not found, %s not made (any ROP renders the variant with 'Hold Shell Open' and 'Flicker On' on)" % (OUT, src_name, new_name))
            continue
        rop = hou.copyNodesTo((src,), out)[0]
        try:
            rop.setName(new_name, unique_name=True)
            rop.setPosition(src.position() + hou.Vector2(3.0, 0.0))
            for toggle, lang, script, val in (("tpreframe", "lpreframe", "preframe", ROP_PRE), ("tpostrender", "lpostrender", "postrender", ROP_POST)):
                rop.parm(script).set(val)
                rop.parm(lang).set("python")
                if rop.parm(toggle) is not None:
                    rop.parm(toggle).set(1)
            pp = rop.parm("RS_outputFileNamePrefix")
            nv = rop_output_path(pp.unexpandedString(), old_tag, new_tag)
            pp.set(nv)
            rop.setComment(ROP_COMMENT)
            rop.setGenericFlag(hou.nodeFlag.DisplayComment, True)
        except Exception:
            rop.destroy()
            raise
        changed("rop: %s/%s created from %s, output %s" % (OUT, new_name, src_name, nv))
    for rop in out.children():
        p = rop.parm("preframe")
        if p is None:
            continue
        cur = p.unexpandedString()
        if "lf_enable" in cur and "hold_open" not in cur and (rop.parm("lpreframe") is None or rop.parm("lpreframe").evalAsString() == "python"):
            p.set(STORY_ROP_PREFIX + cur)
            changed("rop: %s pre-frame also turns Hold Shell Open off" % rop.name())


def step_report():
    n = ctrl()
    st = int(round(n.evalParm("loop_start"))); L = int(round(n.evalParm("loop_frames")))
    beats = hou.session.pearl_beat_frames(n)
    log("beat grid: %d beats per loop, first beats at frames %s ..." % (len(beats), beats[:8]))
    log("set 'Track BPM' (or Advanced > Beats per Loop) on %s once the track is confirmed; %d frames = %.1f s" % (CTRL, L, L / hou.fps()))
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
    if not _CHANGES:
        log("nothing changed, not saving")
        return None
    new = save_target()
    if new != hou.hipFile.path() and os.path.exists(new):
        fail("save: %s already exists; save manually under another name (the changes are applied in the session)" % new)
    hou.hipFile.save(file_name=new)
    log("saved %s (%d changes)" % (new, len(_CHANGES)))
    return new


def run():
    del _CHANGES[:]
    preflight()
    step_engine()
    step_parms()
    step_values()
    step_hold_open()
    step_tree()
    step_rops()
    step_report()


def main(argv=None):
    argv = list(argv or [])
    if argv:
        if not os.path.isfile(argv[0]):
            fail("scene not found: %s" % argv[0])
        if hou.nodeType(hou.ropNodeTypeCategory(), "Redshift_ROP") is None:
            fail("Redshift is not loaded in this session (no Redshift_ROP node type); run from a Houdini shell with the Redshift package")
        hou.hipFile.load(argv[0], suppress_save_prompt=True)
    try:
        if hou.isUIAvailable():
            with hou.undos.group("Pearl v4 light pass"):
                run()
        else:
            run()
    except Exception:
        log("FAILED: do not save. File > Open the original scene again (or Edit > Undo 'Pearl v4 light pass'); nothing has been written to disk.")
        raise
    return step_save()


if hou is not None and __name__ != "apply_v004":
    if __name__ == "__main__" and not hou.isUIAvailable():
        main(sys.argv[1:])          # hython apply_v004.py <scene.hiplc>
    else:
        main()                      # exec()'d in the Houdini Python shell / Source Editor with the scene loaded
