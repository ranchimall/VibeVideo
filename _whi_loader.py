import importlib.util
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WHI_MAIN_PATH = os.path.join(BASE_DIR, "vwhisper", "whi_main.py")

_cached_module = None


def load_whi_main():
    global _cached_module
    if _cached_module is not None:
        return _cached_module

    if not os.path.exists(WHI_MAIN_PATH):
        raise FileNotFoundError(f"Could not find whi_main.py at '{WHI_MAIN_PATH}'.")

    spec = importlib.util.spec_from_file_location("vv_whi_main", WHI_MAIN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    _cached_module = module
    return module