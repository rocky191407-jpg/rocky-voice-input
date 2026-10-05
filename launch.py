"""Start from any working directory (Windows Run registration)."""
import os
from pathlib import Path
import runpy
import sys
root = Path(__file__).resolve().parent
os.chdir(root)
sys.path.insert(0, str(root))
runpy.run_module("app.main", run_name="__main__")
