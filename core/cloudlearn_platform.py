"""Back-compat re-export — Phase 9 (v2.0.0 vyomi rebrand).

The platform module was renamed ``core.cloudlearn_platform`` →
``core.vyomi_platform``. This shim keeps any external script that does
``from core.cloudlearn_platform import CloudLearnPlatform`` working by
re-exporting everything from the new module.

Slated for removal in v3.0. Switch importers to ``core.vyomi_platform``
and the ``VyomiPlatform`` class name when convenient.
"""
from core.vyomi_platform import *  # noqa: F401,F403
from core.vyomi_platform import CloudLearnPlatform  # explicit re-export
