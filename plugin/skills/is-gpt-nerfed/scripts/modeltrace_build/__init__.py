"""Local model enrollment, adapted from ModelTrace (https://github.com/xqy2006/ModelTrace, MIT; see
plugin/assets/modeltrace/LICENSE-ModelTrace.txt) at commit 6cd4a8ff0f3f4e49d6d6969dd2fbadfa1569fde2.

challenge_suite.py is the upstream file unchanged (the 36 reference prompts). builder.py is a pure-Python port of
upstream bank_builder.py, so `nerfed enroll` / `nerfed bank` run inside the numpy-free core; tests/modeltrace_numpy
keeps the numpy originals for the parity test.
"""
