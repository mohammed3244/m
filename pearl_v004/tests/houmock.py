"""
Offline stand-in for the parts of Houdini's `hou` module that the PEARL_ANIM light engine touches.

It lets the engine (the scene's hou.session source) run outside Houdini so the per-frame light levels
can be checked frame by frame.  Keyed channels come from the controller's .chn file (bezier / linear /
constant segments, time in seconds), scalar parms from the .parm file, and hscript `if(...)` expressions
of the form used by lf_activity are evaluated by a tiny translator.

Only what the engine needs is implemented.  It is a test fixture, not a Houdini emulator.
"""
import math
import re
import sys
import types

FPS = 30.0

# ----------------------------------------------------------------------------------------------------
# .parm / .chn parsing
# ----------------------------------------------------------------------------------------------------

def parse_parm_file(text):
    """Return {parm_name: value} for scalar parms.  Values that are channel refs ([ name v ]) keep v."""
    out = {}
    for line in text.splitlines():
        m = re.match(r'^(\w+)\t\[.*?\]\t\((.*)\)\s*$', line)
        if not m:
            continue
        name, body = m.group(1), m.group(2).strip()
        toks = re.findall(r'\[\s*(\w+)\s+([^\]]+?)\s*\]|("(?:[^"\\]|\\.)*")|(\S+)', body)
        vals = []
        for cname, cval, qs, bare in toks:
            if cname:
                vals.append((cname, cval))
            elif qs:
                vals.append((None, qs.strip('"')))
            else:
                vals.append((None, bare))
        if not vals:
            continue
        if len(vals) == 1:
            out[name] = _num(vals[0][1])
            if vals[0][0]:
                out[vals[0][0]] = _num(vals[0][1])
        else:
            for i, (cname, v) in enumerate(vals):
                if cname:
                    out[cname] = _num(v)
            out[name] = [_num(v) for _, v in vals]
    return out


def _num(s):
    if s in ('on', 'off'):
        return 1.0 if s == 'on' else 0.0
    try:
        return float(s)
    except ValueError:
        return s


class Segment(object):
    __slots__ = ('t0', 'length', 'v0', 'v1', 's0', 's1', 'a0', 'a1', 'func')

    def __init__(self, t0, length, v0, v1, s0, s1, a0, a1, func):
        self.t0, self.length, self.v0, self.v1 = t0, length, v0, v1
        self.s0, self.s1, self.a0, self.a1, self.func = s0, s1, a0, a1, func

    def eval(self, t):
        if self.length <= 0.0:
            return self.v0
        u = (t - self.t0) / self.length
        u = min(max(u, 0.0), 1.0)
        if self.func == 'constant':
            return self.v0
        if self.func == 'linear':
            return self.v0 + (self.v1 - self.v0) * u
        # bezier(): cubic with handles of length a0/a1 (seconds) and slopes s0/s1 (value per second)
        p0 = (self.t0, self.v0)
        p1 = (self.t0 + self.a0, self.v0 + self.s0 * self.a0)
        p2 = (self.t0 + self.length - self.a1, self.v1 - self.s1 * self.a1)
        p3 = (self.t0 + self.length, self.v1)
        # solve the time component for the bezier parameter by bisection (monotone in time)
        lo, hi = 0.0, 1.0
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            x = _bez(p0[0], p1[0], p2[0], p3[0], mid)
            if x < t:
                lo = mid
            else:
                hi = mid
        s = 0.5 * (lo + hi)
        return _bez(p0[1], p1[1], p2[1], p3[1], s)


def _bez(a, b, c, d, s):
    m = 1.0 - s
    return m * m * m * a + 3 * m * m * s * b + 3 * m * s * s * c + s * s * s * d


class Channel(object):
    def __init__(self, name, segments, expr, language, default):
        self.name, self.segments, self.expr, self.language, self.default = name, segments, expr, language, default

    def is_keyed(self):
        return bool(self.segments)

    def eval_time(self, t):
        segs = self.segments
        if t <= segs[0].t0:
            return segs[0].v0
        for sg in segs:
            if sg.t0 <= t <= sg.t0 + sg.length:
                return sg.eval(t)
        last = segs[-1]
        return last.v1 if last.length > 0 else last.v0


def parse_chn_file(text):
    """Return {channel_name: Channel}.  Segment times are seconds from the channel start (0 = frame 1)."""
    chans = {}
    for name, body in re.findall(r'\n    channel (\w+) \{(.*?)\n    \}', text, re.S):
        default = 0.0
        md = re.search(r'\n\s+default = ([-\d.e]+)', body)
        if md:
            default = float(md.group(1))
        segs = []
        t = 0.0
        expr, language = None, None
        for sg in re.findall(r'segment \{(.*?)\}(?=\s*(?:segment|$))', body, re.S):
            # the python expression block can contain braces: handle the simple shapes we know
            mlen = re.search(r'length = ([-\d.e]+)', sg)
            length = float(mlen.group(1)) if mlen else 0.0
            mval = re.search(r'value = ([-\d.e]+) ([-\d.e]+)', sg)
            v0, v1 = (float(mval.group(1)), float(mval.group(2))) if mval else (0.0, 0.0)
            msl = re.search(r'slope = ([-\d.e]+) ([-\d.e]+)', sg)
            s0, s1 = (float(msl.group(1)), float(msl.group(2))) if msl else (0.0, 0.0)
            mac = re.search(r'accel = ([-\d.e]+) ([-\d.e]+)', sg)
            a0, a1 = (float(mac.group(1)), float(mac.group(2))) if mac else (length / 3.0, length / 3.0)
            mex = re.search(r'expr = (bezier|linear|constant)\(\)', sg)
            if mex:
                segs.append(Segment(t, length, v0, v1, s0, s1, a0, a1, mex.group(1)))
                t += length
            else:
                mq = re.search(r'expr = "((?:[^"\\]|\\.)*)"(?:\s+language = (\w+))?', sg, re.S)
                if mq:
                    expr = mq.group(1).replace('\\"', '"')
                    language = mq.group(2) or 'hscript'
                else:
                    mb = re.search(r'expr = (\S.*?)(?:\s+language = (\w+))?\s*$', sg, re.S)
                    if mb:
                        expr = mb.group(1).strip().replace('\\"', '"')
                        language = mb.group(2) or 'hscript'
        if not segs and expr is None:
            # python multi-line expression: the simple regex above cannot split it; grab the quoted block
            mq = re.search(r'expr = "(.*)"\s+language = python', body, re.S)
            if mq:
                expr, language = mq.group(1).replace('\\"', '"'), 'python'
        chans[name] = Channel(name, segs, expr, language, default)
    return chans


# ----------------------------------------------------------------------------------------------------
# mock hou
# ----------------------------------------------------------------------------------------------------

class _HMath(object):
    @staticmethod
    def noise1d(p):
        # smooth, deterministic value noise with the same rough statistics as hou.hmath.noise1d
        # (mean ~0.5, sd ~0.1).  Good enough for structural tests; not Houdini's Perlin.
        x, y, z = (float(v) for v in p)
        def h(ix, iy, iz):
            v = math.sin(ix * 127.1 + iy * 311.7 + iz * 74.7) * 43758.5453
            return v - math.floor(v)
        ix, iy, iz = math.floor(x), math.floor(y), math.floor(z)
        fx, fy, fz = x - ix, y - iy, z - iz
        sm = lambda u: u * u * (3 - 2 * u)
        fx, fy, fz = sm(fx), sm(fy), sm(fz)
        def L(a, b, u):
            return a + (b - a) * u
        c = [[[h(ix + i, iy + j, iz + k) for k in (0, 1)] for j in (0, 1)] for i in (0, 1)]
        v = L(L(L(c[0][0][0], c[0][0][1], fz), L(c[0][1][0], c[0][1][1], fz), fy),
              L(L(c[1][0][0], c[1][0][1], fz), L(c[1][1][0], c[1][1][1], fz), fy), fx)
        return 0.5 + (v - 0.5) * 0.35


class MockParm(object):
    def __init__(self, node, name):
        self.node, self.name = node, name

    def evalAtFrame(self, f):
        return self.node.eval_at_frame(self.name, f)

    def eval(self):
        return self.node.eval_at_frame(self.name, self.node.hou.frame())

    def set(self, v):
        self.node.values[self.name] = float(v)
        self.node.channels.pop(self.name, None)


class MockNode(object):
    def __init__(self, hou, values, channels, path='/obj/PEARL_ANIM'):
        self.hou, self.values, self.channels, self._path = hou, dict(values), dict(channels), path
        self.override = {}   # name -> callable(frame) -> value   (simulates an expression put on the parm)

    def path(self):
        return self._path

    def parm(self, name):
        # like hou.Node.parm: None for a parm the node does not have
        if name in self.override or name in self.channels or name in self.values:
            return MockParm(self, name)
        return None

    def evalParm(self, name):
        return self.eval_at_frame(name, self.hou.frame())

    def eval_at_frame(self, name, f):
        if name in self.override:
            return self.override[name](f)
        ch = self.channels.get(name)
        if ch is not None and ch.is_keyed():
            return ch.eval_time((f - 1.0) / FPS)
        if ch is not None and ch.expr is not None:
            return self._eval_expr(ch, f)
        v = self.values.get(name)
        if v is None:
            raise KeyError('parm %s not found on %s' % (name, self._path))
        return v

    def _eval_expr(self, ch, f):
        old = self.hou._frame
        self.hou._frame = f
        try:
            if ch.language == 'python':
                src = ch.expr
                g = {'hou': self.hou, 'math': math}
                body = 'def __expr__():\n' + '\n'.join('    ' + l for l in src.splitlines()) + '\n'
                exec(body, g)
                return g['__expr__']()
            # hscript subset: $F, ch("x"), if(c,a,b), && ||, comparisons, arithmetic, sin()
            e = ch.expr
            e = e.replace('$F', repr(float(f)))
            e = re.sub(r'ch\("([^"]+)"\)', lambda m: repr(float(self.eval_at_frame(m.group(1), f))), e)
            e = e.replace('&&', ' and ').replace('||', ' or ')
            e = re.sub(r'\bif\(', '_if(', e)
            env = {'_if': lambda c, a, b: a if c else b, 'sin': lambda d: math.sin(math.radians(d)),
                   'cos': lambda d: math.cos(math.radians(d)), 'max': max, 'min': min, 'abs': abs,
                   'clamp': lambda v, lo, hi: min(max(v, lo), hi), 'round': lambda v: float(math.floor(v + 0.5)),
                   'floor': math.floor, 'ceil': math.ceil, 'fit': lambda v, a, b, c, d: c + (d - c) * (v - a) / (b - a),
                   'sqrt': math.sqrt, 'pow': pow, 'exp': math.exp}
            return float(eval(e, env))
        finally:
            self.hou._frame = old


class MockHou(object):
    def __init__(self):
        self._frame = 1.0
        self.hmath = _HMath()
        self.session = types.ModuleType('hou.session')
        self._pwd = None

    def frame(self):
        return self._frame

    def setFrame(self, f):
        self._frame = float(f)

    def fps(self):
        return FPS

    def pwd(self):
        return self._pwd


def load_scene(parm_path, chn_path, session_src):
    """Build the mock hou + controller node and exec the engine source into hou.session."""
    hou = MockHou()
    values = parse_parm_file(open(parm_path).read())
    channels = parse_chn_file(open(chn_path).read())
    node = MockNode(hou, values, channels)
    hou._pwd = node
    sys.modules['hou'] = hou
    g = hou.session.__dict__
    g['hou'] = hou
    exec(compile(session_src, '<hou.session>', 'exec'), g)
    return hou, node
