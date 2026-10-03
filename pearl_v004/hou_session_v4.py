# ---- PEARL_ANIM per-light flicker (v4, 2026-10-03): beat-locked, 15 % floor, ramped ----
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
