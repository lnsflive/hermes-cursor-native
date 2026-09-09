"""Install provider adapters at module availability, without eager core imports.

Hermes discovers providers while importing auth/config. A target may therefore
already be executing when the plugin loads. Such a module gets a temporary
attribute-access guard; future imports use a narrowly scoped loader wrapper.
Neither mechanism starts threads or changes Python's global import function.
"""
from __future__ import annotations

import importlib.abc
import sys
import types

_TARGETS = {
    'hermes_cli.auth': ('PROVIDER_REGISTRY', '_resolve_api_key_provider_secret'),
    'hermes_cli.model_setup_flows': ('_model_flow_api_key_provider',),
    'hermes_cli.model_switch_providers': ('_auth_store_has_provider',),
}
_pending = set(_TARGETS)
_busy = set()
_installed = False


def _apply(module):
    data = types.ModuleType.__getattribute__(module, '__dict__')
    name = data.get('__name__')
    if name not in _pending or name in _busy:
        return
    if not all(key in data for key in _TARGETS[name]):
        return
    _busy.add(name)
    try:
        if name == 'hermes_cli.auth':
            from .auth_shim import install_auth_shim, sync_provider_auth_registry
            from providers import get_provider_profile
            profile = get_provider_profile('cursor')
            if profile is None:
                return
            ok = sync_provider_auth_registry(profile) and install_auth_shim()
        elif name == 'hermes_cli.model_setup_flows':
            from .flow_shim import install_model_flow_wrapper
            ok = install_model_flow_wrapper()
        else:
            from .ui_shim import install_picker_credential_shim
            ok = install_picker_credential_shim()
        if ok:
            _pending.discard(name)
            original_class = data.pop('_cursor_original_module_class', None)
            if original_class is not None:
                module.__class__ = original_class
            if not _pending and _finder in sys.meta_path:
                sys.meta_path.remove(_finder)
    finally:
        _busy.discard(name)


def _guard(module):
    data = types.ModuleType.__getattribute__(module, '__dict__')
    _apply(module)
    if data.get('__name__') not in _pending or '_cursor_original_module_class' in data:
        return
    base = type(module)
    class PendingModule(base):
        def __getattribute__(self, key):
            _apply(self)
            return base.__getattribute__(self, key)
    data['_cursor_original_module_class'] = base
    module.__class__ = PendingModule


class CompletionLoader(importlib.abc.Loader):
    def __init__(self, original):
        self.original = original

    def create_module(self, spec):
        create = getattr(self.original, 'create_module', None)
        return create(spec) if create else None

    def exec_module(self, module):
        self.original.exec_module(module)
        _apply(module)

    def __getattr__(self, key):
        return getattr(self.original, key)


class CompletionFinder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname not in _pending:
            return None
        for finder in tuple(sys.meta_path):
            if finder is self:
                continue
            find = getattr(finder, 'find_spec', None)
            spec = find(fullname, path, target) if find else None
            if spec is not None:
                if spec.loader is not None:
                    spec.loader = CompletionLoader(spec.loader)
                return spec
        return None


_finder = CompletionFinder()


def install_defer_hooks():
    global _installed
    if _installed:
        return
    _installed = True
    sys.meta_path.insert(0, _finder)
    for name in tuple(_pending):
        module = sys.modules.get(name)
        if module is not None:
            _guard(module)
