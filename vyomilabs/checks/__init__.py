"""Layer checkers. A checker inspects what the learner built (by the contract names) through the real cloud SDK and reports
PASS / FAIL / BLOCKED per step, using the reference app's step recorder.

Each layer has a module checks/lNN_<slug>.py whose verify(ctx) is registered with @register(NN). Checkers only READ the learner's
resources; they never create or change them, so a check can be run any number of times."""
import importlib
import pkgutil

from .. import ensure_reference_on_path

ensure_reference_on_path()
REGISTRY = {}


def register(layer_id):
    def deco(fn):
        REGISTRY[int(layer_id)] = fn
        return fn
    return deco


def _load_all():
    for m in pkgutil.iter_modules(__path__):
        if m.name.startswith("l") and m.name[1:3].isdigit():
            importlib.import_module(f"{__name__}.{m.name}")


def available():
    _load_all()
    return sorted(REGISTRY)


def run(layer_id, endpoint, region="us-east-1", workspace=None):
    """Run one layer's checker. Returns {layer, status, steps, implemented}."""
    ensure_reference_on_path()
    from facilities.runtime import Ctx, PASS, BLOCKED, FAIL
    _load_all()
    fn = REGISTRY.get(int(layer_id))
    if fn is None:
        return dict(layer=int(layer_id), status=BLOCKED, implemented=False,
                    steps=[dict(component=int(layer_id), name="checker", status=BLOCKED, detail="no checker for this layer yet", secs=0)])
    lines = []
    ctx = Ctx(endpoint, region=region, out=lines.append)
    ctx.workspace = workspace
    ctx.current = int(layer_id)
    fn(ctx)
    return dict(layer=int(layer_id), status=ctx.verdict(int(layer_id)), implemented=True, steps=ctx.subs, log=lines)
