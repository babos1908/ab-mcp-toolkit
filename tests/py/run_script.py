# Runs one prepared tool script (helpers + template, placeholders already
# substituted by ScriptManager) against the fake scriptengine.
#
#   python2.7 run_script.py <fixture.py> <script.py>
#
# The fixture builds the fake world (it runs with `se` = the fake module in
# scope) and may define dump() -> dict, printed after the script as
#   ### STATE ### <json>
# so a test can assert on what the script did, not only on what it printed.
import sys
import os
import json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # worlds.py
sys.path.insert(0, os.path.join(HERE, 'fake_scriptengine'))

import scriptengine as se  # the fake

fixture_path, script_path = sys.argv[1], sys.argv[2]
fx = {'se': se, '__name__': 'fixture'}
execfile(fixture_path, fx)

with open(script_path, 'rb') as f:
    code = f.read()
ns = {'__name__': '__main__'}
exit_code = 0
try:
    exec(compile(code, script_path, 'exec'), ns)
except SystemExit as e:
    exit_code = e.code if isinstance(e.code, int) else 0

sys.stdout.flush()
state = fx['dump']() if 'dump' in fx else {}
state['exitCode'] = exit_code
state['calls'] = se.CALLS
sys.stdout.write("\n### STATE ### " + json.dumps(state) + "\n")
