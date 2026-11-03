"""Compatibility entrypoint for the shared image runtime."""
from pathlib import Path
import runpy

runtime = Path(__file__).resolve().parents[3] / "skill-library/image-runtime/generate.py"
globals().update(runpy.run_path(str(runtime), run_name="__main__" if __name__ == "__main__" else "image_runtime"))
