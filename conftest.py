"""Make the project root importable as `src.*` during tests regardless
of how pytest is invoked."""

import os
import sys

ROOT = os.path.dirname(__file__)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
