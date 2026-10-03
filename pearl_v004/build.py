"""Embed hou_session_v4.py into apply_v004.py (between the ENGINE_SRC markers).  Run after editing the engine."""
import os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__))
eng = open(os.path.join(HERE, 'hou_session_v4.py')).read()
assert "'''" not in eng, "engine must not contain triple single quotes"
ap = os.path.join(HERE, 'apply_v004.py')
s = open(ap).read()
new = re.sub(r"ENGINE_SRC = r'''.*?'''", lambda m: "ENGINE_SRC = r'''" + eng + "'''", s, count=1, flags=re.S)
assert new != s or eng in s, 'marker not found'
open(ap, 'w').write(new)
print('embedded %d bytes of engine into apply_v004.py' % len(eng))
