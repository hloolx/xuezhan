"""Import the approved audio and UI assets in one coordinated Unreal process."""
from pathlib import Path
import runpy

directory = Path(__file__).resolve().parent
runpy.run_path(str(directory / "import_epic_audio.py"), run_name="__main__")
runpy.run_path(str(directory / "import_epic_ui.py"), run_name="__main__")
