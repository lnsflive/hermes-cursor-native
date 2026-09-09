"""Native ``hermes plugins install`` entry point.

Keep one implementation for native plugin installs and the optional standalone
installer. Hermes loads this repository as a package from its plugins directory.
"""

import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def register():
    _provider_name = __name__ + "._provider"
    if _provider_name not in sys.modules:
        _source = Path(__file__).parent / "plugin" / "model-providers" / "cursor"
        _spec = spec_from_file_location(
            _provider_name, _source / "__init__.py", submodule_search_locations=[str(_source)]
        )
        if _spec is None or _spec.loader is None:
            raise ImportError("Cannot load the bundled Cursor provider")
        _provider = module_from_spec(_spec)
        sys.modules[_provider_name] = _provider
        try:
            _spec.loader.exec_module(_provider)
        except Exception:
            sys.modules.pop(_provider_name, None)
            raise
    else:
        _provider = sys.modules[_provider_name]

    cursor = _provider.cursor
    return cursor


# Hermes imports directory providers under this namespace. Keep ordinary
# package discovery (including test collection) free of registration effects.
if __name__.startswith("_hermes_user_provider_"):
    cursor = register()
