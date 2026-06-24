"""Loading this package registers every cloud provider plugin. A new cloud joins
by adding a module here + importing it below — that's the whole change."""
from . import aws, gcp, azure, oracle  # noqa: F401  (import = self-register)
from .registry import dispatch, providers, register, CloudProvider  # noqa: F401

__all__ = ["dispatch", "providers", "register", "CloudProvider"]
