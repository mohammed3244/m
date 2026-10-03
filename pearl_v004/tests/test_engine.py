"""
Frame-by-frame checks of the v4 light engine against the controller data extracted from
untitled_water_realism_v001.hiplc.  Runs outside Houdini (see houmock.py).

    python3 tests/test_engine.py [--plot out.png] [--hip-x DIR]

DIR is the folder holding the extracted hip entries (obj__PEARL_ANIM.parm / .chn).  Defaults to
tests/fixtures.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import houmock  # noqa: E402

MASTER_FRAMES = 541        # frames 1..541 (541 == 1 when the loop is seamless)

# values the apply script sets on /obj/PEARL_ANIM
V4_VALUES = {
    'fl_blackout_depth': 0.85, 'lf_beats': 45.0,
    'lf_floor': 0.15, 'lf_env_attack': 1.0, 'lf_env_release': 2.0,
    'lf_beat_sync': 1.0, 'lf_bpm': 0.0, 'lf_beat_offset': 0.0, 'lf_beat_div': 2.0,
    'lf_beat_darklen': 2.0, 'lf_beat_offbeat': 0.5, 'lf_beat_maxrun': 3.0,
}


def load(xdir, engine_src):
    hou, node = houmock.load_scene(os.path.join(xdir, 'obj__PEARL_ANIM.parm'),
                                   os.path.join(xdir, 'obj__PEARL_ANIM.chn'), engine_src)
    node.values['lf_enable'] = 1.0            # the ROPs switch this on at render time
    node.values.update(V4_VALUES)
    return hou, node


def levels(hou, node):
    out = []
    for f in range(1, MASTER_FRAMES + 1):
        hou.setFrame(f)
        out.append(hou.session.pearl_light_levels(node, f))
    return out


def hold_open(node):
    node.override['lf_activity'] = lambda f: 1.0
    for nm in ('lf_hit', 'lf_keyhold', 'lf_dipA', 'lf_dipB', 'lf_ripple'):
        node.override[nm] = lambda f: 0.0


def check(label, hou, node, lv):
    master = node.values['lm_master']
    norm = [[x / master for x in v] for v in lv]
    floor = node.values['lf_floor']
    problems = []
    # 1. floor: no light below 15 % of its steady level
    for k in range(5):
        m = min(v[k] for v in norm)
        if m < floor - 1e-9:
            problems.append('%s: light %d goes to %.3f (< floor %.2f)' % (label, k, m, floor))
    # 2. loop seamless
    if any(abs(a - b) > 1e-9 for a, b in zip(lv[0], lv[MASTER_FRAMES - 1])):
        problems.append('%s: frame 541 != frame 1 (loop not seamless)' % label)
    # 3. dips start on the beat grid (full depth on a grid frame; the attack frame before it is allowed)
    grid = set(hou.session.pearl_beat_frames(node))
    L = int(node.values['loop_frames']); st = int(node.values['loop_start'])
    beat_len = L / node.values['lf_beats']; div = int(node.values['lf_beat_div'])
    import math
    sub = set()
    for s in range(int(math.ceil(L / (beat_len / div) - 1e-9))):
        sub.add(st + int(math.ceil(s * beat_len / div - 1e-9)) % L)
    def keyed_event_near(f):
        # the artist's keyed accents (hits, apex ripple, dip groups) and the flicker start frame are
        # story events, not grid events
        for g in range(f - 2, f + 2):
            for nm in ('lf_hit', 'lf_ripple', 'lf_dipA', 'lf_dipB'):
                if node.eval_at_frame(nm, g) > 0.0:
                    return True
        return abs(f - node.values.get('fl_start', -99)) <= 1 and 'lf_activity' not in node.override
    for k in range(4):
        starts = [f for f in range(3, MASTER_FRAMES) if norm[f - 1][k] < 0.6 and norm[f - 3][k] >= 0.9]
        off = [f for f in starts if f not in sub and (f + 1) not in sub and not keyed_event_near(f)]   # f+1: f is the attack frame
        if off:
            problems.append('%s: light %d has dips off the grid at frames %s' % (label, k, off[:10]))
    # 4. ramps: a frame at the floor is preceded by a frame at or above it and followed by rising frames
    att, rel = int(node.values['lf_env_attack']), int(node.values['lf_env_release'])
    for k in range(4):
        for f in range(2, MASTER_FRAMES - rel - 1):
            cur, prev = norm[f - 1][k], norm[f - 2][k]
            if node.eval_at_frame('lf_hit', f - 1) > 0.0 or node.eval_at_frame('lf_ripple', f - 1) > 0.0:
                continue                                   # keyed hero flash on the frame before: no ramp by design
            if cur <= floor + 1e-9 and prev > 0.99:
                if att > 0:
                    problems.append('%s: light %d jumps 1.0 -> floor at frame %d with no attack ramp' % (label, k, f))
                    break
    # 5. dark statistics (information)
    at_floor = sum(1 for v in norm if min(v[:4]) <= floor + 1e-9)
    dark_main = [sum(1 for v in norm if v[k] < 0.6) for k in range(4)]
    stats = 'frames with a main light at the floor: %d / %d; frames per light under 60%%: %s; min water %.2f; max key %.2f' % (
        at_floor, L, dark_main, min(v[4] for v in norm), max(v[0] for v in norm))
    return problems, stats


def plot(path, story, held, master, grid):
    """Dependency-free SVG: one row per light, story loop on the left, hold-open loop on the right."""
    names = ['key (rslight2)', 'dome6', 'dome7', 'grid', 'water']
    W, H, ML, MT, GAP = 820, 120, 60, 40, 30
    cols = [(story, 'story loop (shell opens / closes)'), (held, 'hold-open loop (shell held open)')]
    width = ML + (W + GAP) * 2
    height = MT + (H + GAP) * 5 + 20
    out = ['<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" font-family="sans-serif" font-size="11">' % (width, height),
           '<rect width="100%%" height="100%%" fill="white"/>',
           '<text x="%d" y="22" font-size="14">PEARL_ANIM v4 light levels: multiplier of the steady light, red dashes = 15 %% floor, grey ticks = beats (45 per 540 f = 150 BPM)</text>' % ML]
    ymax = 2.0
    for col, (lv, title) in enumerate(cols):
        x0 = ML + col * (W + GAP)
        out.append('<text x="%d" y="%d" font-size="12">%s</text>' % (x0, MT - 6, title))
        for k in range(5):
            y0 = MT + k * (H + GAP)
            out.append('<rect x="%d" y="%d" width="%d" height="%d" fill="#fafafa" stroke="#ccc"/>' % (x0, y0, W, H))
            for b in grid:
                bx = x0 + (b - 1) / 540.0 * W
                out.append('<line x1="%.1f" y1="%d" x2="%.1f" y2="%d" stroke="#ddd" stroke-width="0.6"/>' % (bx, y0, bx, y0 + H))
            yf = y0 + H - 0.15 / ymax * H
            out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#d33" stroke-dasharray="4 3" stroke-width="0.8"/>' % (x0, yf, x0 + W, yf))
            y1 = y0 + H - 1.0 / ymax * H
            out.append('<line x1="%d" y1="%.1f" x2="%d" y2="%.1f" stroke="#bbb" stroke-width="0.6"/>' % (x0, y1, x0 + W, y1))
            pts = []
            for f in range(1, MASTER_FRAMES + 1):
                v = min(ymax, lv[f - 1][k] / master)
                pts.append('%.1f,%.1f' % (x0 + (f - 1) / 540.0 * W, y0 + H - v / ymax * H))
            out.append('<polyline fill="none" stroke="#1f77b4" stroke-width="1" points="%s"/>' % ' '.join(pts))
            out.append('<text x="%d" y="%d" transform="rotate(-90 %d %d)" text-anchor="middle">%s</text>' % (x0 - 10, y0 + H / 2, x0 - 10, y0 + H / 2, names[k]))
            out.append('<text x="%d" y="%d" fill="#666">2.0</text><text x="%d" y="%d" fill="#666">1.0</text><text x="%d" y="%d" fill="#666">0</text>' % (x0 - 48, y0 + 10, x0 - 48, y1 + 4, x0 - 48, y0 + H))
            if k == 4:
                for fr in (1, 100, 200, 300, 400, 540):
                    out.append('<text x="%.1f" y="%d" text-anchor="middle" fill="#666">%d</text>' % (x0 + (fr - 1) / 540.0 * W, y0 + H + 14, fr))
    out.append('</svg>')
    open(path, 'w').write('\n'.join(out))
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--hip-x', default=os.path.join(HERE, 'fixtures'))
    ap.add_argument('--engine', default=os.path.join(HERE, '..', 'hou_session_v4.py'))
    ap.add_argument('--plot', default=None)
    ap.add_argument('--no-regress', action='store_true', help='skip the v4-reduces-to-v3 check')
    a = ap.parse_args()
    src = open(a.engine).read()
    hou, node = load(a.hip_x, src)
    master = node.values['lm_master']
    story = levels(hou, node)
    p1, s1 = check('story', hou, node, story)
    hold_open(node)
    held = levels(hou, node)
    p2, s2 = check('hold-open', hou, node, held)
    print('story    :', s1)
    print('hold-open:', s2)
    if a.plot:
        print('plot:', plot(a.plot, story, held, master, hou.session.pearl_beat_frames(node)))
    probs = p1 + p2
    if not a.no_regress:
        d = test_v4_reduces_to_v3(a.hip_x)
        print('regress  : v4 with beat sync off, floor 0, ramps 0 vs v3: %s' % ('identical on all 541 frames' if not d else 'differs at frames %s' % d[:20]))
        if d:
            probs.append('v4 does not reduce to v3 (frames %s)' % d[:10])
    for p in probs:
        print('FAIL', p)
    print('OK' if not probs else '%d problem(s)' % len(probs))
    return 1 if probs else 0




def test_v4_reduces_to_v3(xdir=None):
    """With beat sync off, floor 0, ramps 0 and the v001 values, v4 must evaluate exactly like v3 on every frame."""
    xdir = xdir or os.path.join(HERE, 'fixtures')
    v3 = open(os.path.join(xdir, 'hou_session_v3.py')).read()
    v4 = open(os.path.join(HERE, '..', 'hou_session_v4.py')).read()
    out = []
    for src in (v3, v4):
        hou, node = houmock.load_scene(os.path.join(xdir, 'obj__PEARL_ANIM.parm'), os.path.join(xdir, 'obj__PEARL_ANIM.chn'), src)
        node.values['lf_enable'] = 1.0
        if src is v4:
            node.values.update({'lf_floor': 0.0, 'lf_env_attack': 0.0, 'lf_env_release': 0.0, 'lf_beat_sync': 0.0})
        out.append(levels(hou, node))
    diff = [f + 1 for f, (a, b) in enumerate(zip(*out)) if any(abs(x - y) > 1e-9 for x, y in zip(a, b))]
    return diff


if __name__ == '__main__':
    sys.exit(main())
