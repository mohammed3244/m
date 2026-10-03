
# ---- PEARL_ANIM per-light flicker (v3, 2026-09-23): every light on its own clock ----
# Levels for [key rslight2, dome6, dome7, grid, water]. All reads are loop-local, so frame
# loop_start + loop_frames == loop_start. Each light reads the keyed envelope at its own time offset,
# strobes on its own step length / seed, and swells on its own slow period.
import math

_PL_NAMES = ("key", "dome6", "dome7", "grid")

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

def _pearl_light_levels_raw(n, frame):
    ev = n.evalParm
    if not ev("lf_enable"):
        return [1.0, 1.0, 1.0, 1.0, 1.0]
    st = int(round(ev("loop_start"))); L = max(1, int(round(ev("loop_frames"))))
    fi = int(math.floor(frame - st + 1e-6))
    def loc(off):
        i = int(fi - off) % L
        return i, st + i
    def ch(name, f):
        return n.parm(name).evalAtFrame(f)
    seed = ev("lf_seed") * 1000.0
    thr = ev("lf_dark_thresh"); swell_amt = ev("lf_swell_amt"); casc = ev("lf_cascade")
    lv = [1.0, 1.0, 1.0, 1.0]; hv = [1.0, 1.0, 1.0, 1.0]; mins = [0.0] * 4
    hold = ch("lf_keyhold", loc(0)[1]) > 0.5
    for k, nm in enumerate(_PL_NAMES):
        mins[k] = ev("lf_min_" + nm)
        d = abs(int(round(ev("lf_off_" + nm))))
        a = max(0.0, min(1.0, ch("lf_activity", loc(d)[1]), ch("lf_activity", loc(0)[1]), ch("lf_activity", loc(-d)[1])))   # enters d late, leaves d early
        i = (loc(0)[0] + 17 * k) % L                                                                # own phase
        if a <= 1e-4:
            continue
        step = max(1, int(round(ev("lf_step_" + nm))))
        s = i // step
        sd = seed + 101.0 + 37.0 * k
        hv[k] = _pl_h(sd, s)
        ok = (s % 3 != 1) if step <= 2 else ((s % 2 == 0) and (i % step) < 4)   # dark runs <= 4 frames
        if s == (L - 1) // step:
            ok = False                                                            # last step before the wrap stays lit (no long run across the loop)
        lvl = 1.0
        strobe_dark = ok and hv[k] < ev("lf_prob_" + nm) * a and not (k == 0 and hold)
        if strobe_dark:
            lvl = 1.0 - a * (1.0 - mins[k])
        per = ev("lf_swell_" + nm)
        if per > 0.5 and swell_amt > 0.0 and not (k == 0 and hold):
            lvl *= 1.0 + swell_amt * a * _pl_swell(i, L, per, sd + 5.0)
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


# ---- Light Mix (PEARL_ANIM "Light Mix" tab): per-light brightness, master, and flicker blend ----
_PL_MIX = ("lm_key", "lm_dome6", "lm_dome7", "lm_grid", "lm_water")

def pearl_light_levels(n, frame):
    raw = _pearl_light_levels_raw(n, frame)
    ev = n.evalParm
    mix = max(0.0, min(1.0, ev("lm_flicker_mix")))          # 0 = steady light, 1 = full flicker
    master = max(0.0, ev("lm_master"))
    bo = _pl_blackout(n, frame)
    return [(1.0 + mix * (v - 1.0)) * max(0.0, ev(p)) * master * (1.0 - bo) for v, p in zip(raw, _PL_MIX)]

def _pl_blackout(n, frame):
    # full-dark flicker: in short steps the whole rig drops to black (fl_blackout_depth), then back to full.
    # Never before Start Frame, never on the white hits / apex ripple / key-hold hero moments,
    # at most fl_blackout_maxrun dark steps in a row, last step before the loop wrap stays lit.
    ev = n.evalParm
    amt = ev("fl_blackout")
    if amt <= 0.0 or not ev("lf_enable"):
        return 0.0
    st = int(round(ev("loop_start"))); L = max(1, int(round(ev("loop_frames"))))
    i = int(math.floor(frame - st + 1e-6)) % L
    F = st + i
    act = max(0.0, min(1.0, n.parm("lf_activity").evalAtFrame(F)))
    if act <= 1e-4:
        return 0.0
    if n.parm("lf_keyhold").evalAtFrame(F) > 0.5 or n.parm("lf_hit").evalAtFrame(F) > 0.0 or n.parm("lf_ripple").evalAtFrame(F) > 0.0:
        return 0.0
    step = max(1, int(round(ev("fl_blackout_step"))))
    nsteps = (L - 1) // step + 1
    s = i // step
    if s == nsteps - 1:
        return 0.0
    seed = ev("lf_seed") * 1000.0 + 523.0
    p = amt * act
    run = max(1, int(round(ev("fl_blackout_maxrun"))))
    def raw(c):
        return _pl_h(seed, c % nsteps) < p
    if raw(s) and not all(raw(s - k) for k in range(1, run + 1)):
        return max(0.0, min(1.0, ev("fl_blackout_depth")))
    return 0.0
