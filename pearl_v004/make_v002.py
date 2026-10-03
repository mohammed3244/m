# -*- coding: utf-8 -*-
"""
Build untitled_water_realism_v002.hiplc from the v001 file WITHOUT Houdini, applying exactly the change
that apply_v004.py applies inside Houdini (both read the spec from apply_v004.py).

    python3 make_v002.py <v001.hiplc> <v002.hiplc>

The file is edited record by record (see hipio.py): the hou.session module, the controller's spare
parameter interface / values / channels, the tree time-shift and glow window, two new ROPs and the
/out node order.  Everything else is copied byte for byte.  The result is re-read and the edited
controller channels are evaluated with the offline harness before the file is reported as good.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'tests'))
import hipio          # noqa: E402
import apply_v004 as S   # noqa: E402  (the spec; hou is None offline)

CTRL_P = S.CTRL.lstrip('/')          # 'obj/PEARL_ANIM'
TREE_TS = S.TREE_TIMESHIFT.lstrip('/')
TREE_C = S.TREE_CTRL.lstrip('/')


def log(msg):
    print('[make v002] ' + msg)


# ---------------------------------------------------------------------------------------------------
# text helpers for Houdini's node formats
# ---------------------------------------------------------------------------------------------------
def q(s):
    """Quote for dialog-script / .chn: backslash and double quote escaped."""
    return s.replace('\\', '\\\\').replace('"', '\\"')


def ds_block(spec, ind):
    name, label, kind, default, lo, hi, help_ = spec
    t = {'float': 'float', 'int': 'integer', 'toggle': 'toggle'}[kind]
    d = ('%d' % int(default)) if kind in ('int', 'toggle') else S._num(default)
    lines = ['%sparm {' % ind,
             '%s    name    "%s"' % (ind, name),
             '%s    label   "%s"' % (ind, q(label)),
             '%s    type    %s' % (ind, t),
             '%s    default { "%s" }' % (ind, d)]
    if help_:
        lines.append('%s    help    "%s"' % (ind, q(help_)))
    if kind != 'toggle':
        lo_s = ('%d' % int(lo)) if kind == 'int' else S._num(lo)
        hi_s = ('%d' % int(hi)) if kind == 'int' else S._num(hi)
        lines.append('%s    range   { %s %s }' % (ind, lo_s, hi_s))
    lines.append('%s}' % ind)
    return '\n'.join(lines) + '\n'


def ds_find_block(text, name):
    """(start, end, indent) of the `parm { name "<name>" ... }` block in a dialog script."""
    m = re.search(r'\n([ \t]*)parm \{\n[ \t]*name[ \t]+"%s"\n' % re.escape(name), text)
    if not m:
        raise KeyError('dialog script: parm %r not found' % name)
    ind = m.group(1)
    start = m.start() + 1
    end = text.index('\n' + ind + '}\n', start) + len(ind) + 3
    return start, end, ind


def ds_insert_after(text, anchor, specs):
    for spec in specs:
        if re.search(r'name[ \t]+"%s"\n' % re.escape(spec[0]), text):
            continue
        _s, e, ind = ds_find_block(text, anchor)
        text = text[:e] + ds_block(spec, ind) + text[e:]
        anchor = spec[0]
    return text


def ds_label(text, name):
    s, e, _ = ds_find_block(text, name)
    m = re.search(r'label[ \t]+"((?:[^"\\]|\\.)*)"', text[s:e])
    return m.group(1).replace('\\"', '"')


def parm_line(name, value, kind):
    if kind == 'toggle':
        v = '"on"' if int(value) else '"off"'
    elif kind == 'int':
        v = '%d' % int(value)
    elif kind == 'chan':
        v = '[ %s\t%s ]' % (name, value)
    else:
        v = S._num(value)
    return '%s\t[ 0\tlocks=0 ]\t(\t%s\t)' % (name, v)


def parm_find(text, name):
    m = re.search(r'(?m)^%s\t\[[^\]]*\]\t\((.*)\)[ \t]*$' % re.escape(name), text)
    if not m:
        raise KeyError('.parm: %r not found' % name)
    return m


def parm_insert_after(text, anchor, lines):
    m = parm_find(text, anchor)
    pos = m.end()
    new = ''.join('\n' + l for l in lines if not re.search(r'(?m)^%s\t' % re.escape(l.split('\t')[0]), text))
    return text[:pos] + new + text[pos:]


def parm_set_value(text, name, value_text):
    m = parm_find(text, name)
    inner = m.group(1)
    if '[' in inner:
        raise ValueError('.parm: %s has a channel, not setting a plain value' % name)
    return text[:m.start(1)] + '\t%s\t' % value_text + text[m.end(1):]


def parm_make_channel(text, name):
    """Turn `name ( value )` into `name ( [ name value ] )` so a channel in .chn drives it."""
    m = parm_find(text, name)
    inner = m.group(1).strip()
    if inner.startswith('['):
        return text
    return text[:m.start(1)] + '\t[ %s\t%s ]\t' % (name, inner) + text[m.end(1):]


def chn_expr_block(name, expr, python=False):
    lang = ' language = python' if python else ''
    return ('    channel %s {\n      lefttype = extend\n      righttype = extend\n      flags = 0\n'
            '      segment { length = 0 expr = "%s"%s }\n    }\n' % (name, q(expr), lang))


def chn_rename(text, old, new):
    pat = '\n    channel %s {' % old
    if pat not in text:
        raise KeyError('.chn: channel %r not found' % old)
    if ('\n    channel %s {' % new) in text:
        raise ValueError('.chn: channel %r already exists' % new)
    return text.replace(pat, '\n    channel %s {' % new, 1)


def chn_append(text, block):
    tail = text.rstrip('\n')
    if not tail.endswith('}'):
        raise ValueError('.chn: unexpected tail %r' % tail[-20:])
    i = tail.rfind('\n  }')
    if i < 0:
        raise ValueError('.chn: closing brace not found')
    return tail[:i] + '\n' + block + '  }\n'


def chn_set_expr(text, name, old_expr, new_expr):
    pat = 'expr = "%s"' % q(old_expr)
    s = text.index('\n    channel %s {' % name)
    e = text.index('\n    }', s)
    blk = text[s:e]
    if pat not in blk:
        raise ValueError('.chn: channel %s does not hold the expected expression' % name)
    return text[:s] + blk.replace(pat, 'expr = "%s"' % q(new_expr)) + text[e:]


# ---------------------------------------------------------------------------------------------------
def build(src, dst):
    hip = hipio.Hip(src)
    log('read %s: %d records' % (src, len(hip.recs)))

    # 1. engine --------------------------------------------------------------------------------------
    hs = hip.text('.hou.session')
    if 'def pearl_light_levels' not in hs:
        raise RuntimeError('.hou.session does not hold the v3 light engine')
    if S.ENGINE_MARK in hs:
        log('engine: already v4')
    else:
        hip.set_text('.hou.session', S.ENGINE_SRC)
        log('engine: v4 installed')

    # 2. controller interface ------------------------------------------------------------------------
    ds = hip.text(CTRL_P + '.spareparmdef')
    ds = ds_insert_after(ds, 'fl_blackout_step', S.PARMS_FLICKER)
    ds = ds_insert_after(ds, 'glow', S.PARMS_TIMING)
    for name, _expr in S.HOLD_SWITCH:
        label = ds_label(ds, name)
        ds = ds_insert_after(ds, name, [(S.anim_name(name), S.anim_label(label), 'float', 0.0, -1.0, 1.0, S.anim_help(name))])
    s_, e_, _i = ds_find_block(ds, 'lf_beats')
    blk = ds[s_:e_]
    if S.LF_BEATS_HELP_OLD_MARK in blk:
        blk = re.sub(r'help[ \t]+"[^"]*"', 'help    "%s"' % q(S.LF_BEATS_HELP), blk)
        ds = ds[:s_] + blk + ds[e_:]
    hip.set_text(CTRL_P + '.spareparmdef', ds)
    log('parms: interface updated (%d flicker, %d timing, %d story-key parms)' % (len(S.PARMS_FLICKER), len(S.PARMS_TIMING), len(S.HOLD_SWITCH)))

    # 3. controller values ---------------------------------------------------------------------------
    pm = hip.text(CTRL_P + '.parm')
    pm = parm_insert_after(pm, 'fl_blackout_step', [parm_line(n, d, k) for n, _l, k, d, _lo, _hi, _h in S.PARMS_FLICKER])
    pm = parm_insert_after(pm, 'glow', [parm_line(n, d, k) for n, _l, k, d, _lo, _hi, _h in S.PARMS_TIMING])
    for name, _expr in S.HOLD_SWITCH:
        pm = parm_insert_after(pm, name, [parm_line(S.anim_name(name), '0', 'chan')])
    for name, val in S.V4_VALUES.items():
        pm = parm_set_value(pm, name, S._num(val))
    hip.set_text(CTRL_P + '.parm', pm)
    log('values: fl_blackout_depth %s, lf_beats %s' % (S.V4_VALUES['fl_blackout_depth'], S.V4_VALUES['lf_beats']))

    # 4. controller channels: keys -> _anim, switch expressions on the originals -----------------------
    ch = hip.text(CTRL_P + '.chn')
    for name, expr in S.HOLD_SWITCH:
        ch = chn_rename(ch, name, S.anim_name(name))
        ch = chn_append(ch, chn_expr_block(name, expr))
    ch = chn_set_expr(ch, 'lf_activity', S.LF_ACTIVITY_OLD, S.LF_ACTIVITY_NEW)
    hip.set_text(CTRL_P + '.chn', ch)
    log('hold-open: %d story channels moved to story-key parms, switch expressions set, lf_activity wrapped' % len(S.HOLD_SWITCH))

    # 5. tree: time shift ping-pong + glow window -----------------------------------------------------
    d = hip.text(TREE_TS + '.def')
    if 'bypass on' not in d:
        raise RuntimeError('%s is not bypassed as expected' % TREE_TS)
    hip.set_text(TREE_TS + '.def', d.replace('bypass on', 'bypass off', 1))
    p = hip.text(TREE_TS + '.parm')
    for name, want in (('method', '"byframe"'), ('integerframe', '"on"')):
        if parm_find(p, name).group(1).strip() != want:
            raise RuntimeError('%s/%s is %s, expected %s' % (TREE_TS, name, parm_find(p, name).group(1).strip(), want))
    hip.set_text(TREE_TS + '.parm', parm_make_channel(p, 'frame'))
    hip.set_text(TREE_TS + '.chn', chn_append(hip.text(TREE_TS + '.chn'), chn_expr_block('frame', S.TREE_TIMESHIFT_EXPR)))
    log('tree: %s un-bypassed, frame = ping-pong while held open' % TREE_TS)
    p = hip.text(TREE_C + '.parm')
    c = hip.text(TREE_C + '.chn')
    for name, held in S.TREE_GLOW_WINDOW:
        cur = parm_find(p, name).group(1).strip()
        if cur.startswith('['):
            raise RuntimeError('%s/%s already has a channel' % (TREE_C, name))
        p = parm_make_channel(p, name)
        c = chn_append(c, chn_expr_block(name, S.tree_glow_expr(float(cur), held)))
        log('tree: %s/%s = %s while held open (story value %s)' % (TREE_C, name, S._num(held), cur))
    hip.set_text(TREE_C + '.parm', p)
    hip.set_text(TREE_C + '.chn', c)

    # 6. ROPs ---------------------------------------------------------------------------------------
    order = hip.text('out.order').split('\n')
    names = [n for n in order[1:] if n]
    last_out = [r for r in hip.recs if r.name.startswith(b'out/')][-1].name
    for src_name, new_name, old_tag, new_tag in S.ROPS:
        if new_name in names:
            log('rop: %s already present' % new_name)
            continue
        src_recs = hip.node_records('out/' + src_name)
        if not src_recs:
            log('rop: WARNING out/%s not found, %s not made' % (src_name, new_name))
            continue
        after = last_out
        for r in src_recs:
            suffix = r.name[len('out/' + src_name):]
            body = r.body
            if suffix == b'.def':
                t = r.text
                m = re.search(r'(?m)^position (-?[\d.]+) (-?[\d.]+)$', t)
                t = t[:m.start()] + 'position %s %s' % (S._num(float(m.group(1)) + 3.0), m.group(2)) + t[m.end():]
                t = re.sub(r'(?m)^comment ""$', 'comment "%s"' % q(S.ROP_COMMENT), t, count=1)
                body = t.encode('utf-8')
            elif suffix == b'.parm':
                t = r.text
                for pname, val in (('preframe', S.ROP_PRE), ('postrender', S.ROP_POST), ('lpreframe', 'python'), ('lpostrender', 'python'), ('tpreframe', '"on"'), ('tpostrender', '"on"')):
                    m = parm_find(t, pname)
                    # a string with whitespace / newlines is written double-quoted with \" and \n escapes (like VEX snippets)
                    v = val if pname in ('lpreframe', 'lpostrender', 'tpreframe', 'tpostrender') else '"%s"' % q(val).replace('\n', '\\n')
                    t = t[:m.start(1)] + '\t%s\t' % v + t[m.end(1):]
                m = parm_find(t, 'RS_outputFileNamePrefix')
                t = t[:m.start(1)] + '\t%s\t' % S.rop_output_path(m.group(1).strip(), old_tag, new_tag) + t[m.end(1):]
                body = t.encode('utf-8')
            new = hipio.Record(b'out/' + new_name.encode() + suffix, r.mtime, body, r.magic)
            hip.insert_after(after, new)
            after = new.name
        last_out = after
        names.append(new_name)
        log('rop: out/%s created from %s' % (new_name, src_name))
    hip.set_text('out.order', '%d\n%s\n' % (len(names), '\n'.join(names)))

    hip.save(dst)
    log('wrote %s (%d bytes)' % (dst, os.path.getsize(dst)))
    return hip


# ---------------------------------------------------------------------------------------------------
def verify(src, dst):
    """Re-read the result and evaluate the edited controller with the offline harness."""
    import houmock
    a, b = hipio.read(src), hipio.read(dst)
    log('verify: %d -> %d records; %d bodies changed, %d added' % (
        len(a), len(b), sum(1 for r in a if r.name in {x.name for x in b} and next(x for x in b if x.name == r.name).body != r.body),
        len(b) - len(a)))
    bi = {r.name: r for r in b}
    problems = []
    # untouched records are byte-identical
    touched = {b'.hou.session', (CTRL_P + '.spareparmdef').encode(), (CTRL_P + '.parm').encode(), (CTRL_P + '.chn').encode(),
               (TREE_TS + '.def').encode(), (TREE_TS + '.parm').encode(), (TREE_TS + '.chn').encode(),
               (TREE_C + '.parm').encode(), (TREE_C + '.chn').encode(), b'out.order'}
    for r in a:
        if r.name not in touched and bi[r.name].body != r.body:
            problems.append('record %r changed unexpectedly' % r.name)
    # harness: original vs edited controller, hold_open off must be identical, on must hold
    tmp = os.path.join(HERE, 'tests', '_v002_ctrl')
    os.makedirs(tmp, exist_ok=True)
    for recs, tag in ((a, 'v001'), (b, 'v002')):
        for suf in ('.parm', '.chn'):
            open(os.path.join(tmp, 'obj__PEARL_ANIM%s_%s' % (suf, tag)), 'wb').write({r.name: r for r in recs}[(CTRL_P + suf).encode()].body)
    v3 = {r.name: r for r in a}[b'.hou.session'].text
    v4 = bi[b'.hou.session'].text
    h1, n1 = houmock.load_scene(os.path.join(tmp, 'obj__PEARL_ANIM.parm_v001'), os.path.join(tmp, 'obj__PEARL_ANIM.chn_v001'), v3)
    h2, n2 = houmock.load_scene(os.path.join(tmp, 'obj__PEARL_ANIM.parm_v002'), os.path.join(tmp, 'obj__PEARL_ANIM.chn_v002'), v4)
    for n in (n1, n2):
        n.values['lf_enable'] = 1.0
    frames = range(1, 542)
    chans = [nm for nm, _ in S.HOLD_SWITCH] + ['lf_activity']
    for nm in chans:
        d = [f for f in frames if abs(n1.eval_at_frame(nm, f) - n2.eval_at_frame(nm, f)) > 1e-9]
        if d:
            problems.append('hold_open off: %s differs from v001 at frames %s' % (nm, d[:8]))
    for nm in [n for n, _l, _k, _d, _lo, _hi, _h in S.PARMS_FLICKER + S.PARMS_TIMING]:
        if n2.parm(nm) is None:
            problems.append('v002 controller has no parm %s' % nm)
    n2.values['hold_open'] = 1.0
    want = {'close_amount': 0.0, 'pearl_in': 0.0, 'pearl_out': 1.0, 'glow': 1.0, 'lf_hit': 0.0, 'lf_keyhold': 0.0,
            'lf_dipA': 0.0, 'lf_dipB': 0.0, 'lf_ripple': 0.0, 'lf_activity': 1.0}
    for nm, w in want.items():
        d = [f for f in frames if abs(n2.eval_at_frame(nm, f) - w) > 1e-9]
        if d:
            problems.append('hold_open on: %s is not %s at frames %s' % (nm, w, d[:8]))
    n2.values['hold_open_pearl'] = 1.0
    for nm in ('pearl_in', 'pearl_out'):
        d = [f for f in frames if abs(n1.eval_at_frame(nm, f) - n2.eval_at_frame(nm, f)) > 1e-9]
        if d:
            problems.append('hold_open + keep pearl events: %s differs from v001 at frames %s' % (nm, d[:8]))
    n2.values['hold_open_pearl'] = 0.0
    n2.values['hold_open_breath'] = 1.0
    cv = [n2.eval_at_frame('close_amount', f) for f in frames]
    if abs(cv[0]) > 1e-9 or abs(cv[540]) > 1e-9 or abs(min(cv) + 0.068735732) > 1e-6 or abs(cv[270] - min(cv)) > 1e-9:
        problems.append('breath: close_amount is not a 0 -> -0.0687 -> 0 loop (f1 %s, f271 %s, f541 %s)' % (cv[0], cv[270], cv[540]))
    n2.values['hold_open_breath'] = 0.0
    # tree time shift expression, evaluated with the harness on a fake node carrying the controller values
    tsn = houmock.MockNode(h2, {}, {})
    tsn.channels['frame'] = houmock.Channel('frame', [], S.TREE_TIMESHIFT_EXPR.replace('/obj/PEARL_ANIM/', ''), 'hscript', 0.0)
    tsn.values.update({k: n2.values[k] for k in ('hold_open', 'hold_open_tree_from', 'loop_frames', 'loop_start')})
    tsn.values['hold_open'] = 0.0
    if any(abs(tsn.eval_at_frame('frame', f) - f) > 1e-9 for f in frames):
        problems.append('tree time shift is not pass-through with hold_open off')
    tsn.values['hold_open'] = 1.0
    tv = [tsn.eval_at_frame('frame', f) for f in frames]
    a0 = n2.values['hold_open_tree_from']
    if tv[0] != a0 or tv[540] != a0 or tv[270] != a0 + 270 or min(tv) < a0 or max(tv) > a0 + 270 or any(abs(tv[i + 1] - tv[i]) != 1 for i in range(540)):
        problems.append('tree time shift ping-pong wrong: f1 %s f271 %s f541 %s min %s max %s' % (tv[0], tv[270], tv[540], min(tv), max(tv)))
    # light levels with the v4 engine on the v002 controller, both modes
    import test_engine
    n2.values['hold_open'] = 0.0
    p1, s1 = test_engine.check('v002 story', h2, n2, test_engine.levels(h2, n2))
    n2.values['hold_open'] = 1.0
    p2, s2 = test_engine.check('v002 hold-open', h2, n2, test_engine.levels(h2, n2))
    problems += p1 + p2
    log('verify: story     %s' % s1)
    log('verify: hold-open %s' % s2)
    # ROP records
    for _s, new_name, _o, _n in S.ROPS:
        for suf in ('.init', '.def', '.parm', '.chn', '.userdata', '.spareparmdef'):
            if ('out/%s%s' % (new_name, suf)).encode() not in bi:
                problems.append('missing record out/%s%s' % (new_name, suf))
        t = bi[('out/%s.parm' % new_name).encode()].text
        for needle in ('hold_open', 'lf_enable', 'open_loop'):
            if needle not in t:
                problems.append('out/%s.parm does not mention %s' % (new_name, needle))
    for pr in problems:
        log('PROBLEM ' + pr)
    return problems


def main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 2
    src, dst = argv[0], argv[1]
    if os.path.abspath(src) == os.path.abspath(dst):
        raise SystemExit('refusing to overwrite the source file')
    build(src, dst)
    probs = verify(src, dst)
    print('OK' if not probs else '%d problem(s)' % len(probs))
    return 1 if probs else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
