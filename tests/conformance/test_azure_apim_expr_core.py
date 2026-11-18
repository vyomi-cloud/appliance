"""APIM policy-expression interpreter (core/azure_apim_expr_core.py): the supported C# subset, and honest errors outside it. No network."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
from core import azure_apim_expr_core as E  # noqa: E402

fails = 0


def check(name, got, want):
    global fails
    ok = got == want
    fails += 0 if ok else 1
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'' if ok else f' :: got {got!r} want {want!r}'}")


H = E.headers_obj({"x-deny": "1", "Authorization": "Bearer a.b.c", "X-Amount": "700"})
ENV = {"context": E.Obj({"Request": E.Obj({"Headers": H, "Method": "POST", "Body": E.body_obj(b'{"a": {"b": 3}, "tags": ["x", "y"]}')}),
                         "Variables": E.Obj({}, {"GetValueOrDefault": lambda a: {"n": 5}.get(a[0], a[1] if len(a) > 1 else None)})})}
T = [
    ('@(context.Request.Headers.GetValueOrDefault("x-deny","") == "1")', True),
    ('@(context.Request.Headers.GetValueOrDefault("X-DENY","") == "1")', True),
    ('@(context.Request.Method.ToLower() + "-" + 3)', "post-3"),
    ('@(int.Parse(context.Request.Headers.GetValueOrDefault("x-amount","0")) > 500 && !context.Request.Headers.ContainsKey("x-manager"))', True),
    ('@(context.Request.Headers.GetValueOrDefault("zz", "dflt").ToUpper())', "DFLT"),
    ('@{ var a = 2; if (a > 1) { return "big"; } return "small"; }', "big"),
    ('@{ var t = 0; foreach (var x in new string[]{"a","bb","ccc"}) { t = t + x.Length; } return t; }', 6),
    ('@(context.Request.Body.As<JObject>()["a"]["b"])', 3),
    ('@(context.Request.Body.As<JObject>()["tags"].Any(t => t == "y"))', True),
    ('@(Regex.IsMatch("abc123", "^[a-z]+\\\\d+$"))', True),
    ('@(Regex.Match("order-4412", "(\\\\d+)").Groups[1])', "4412"),
    ('@((string)null ?? "d")', "d"),
    ('@(context.Request.Headers.GetValueOrDefault("zz", "").Length == 0 ? "empty" : "set")', "empty"),
    ('@(string.Join(",", new string[]{"a","b"}))', "a,b"),
    ('@(context.Variables.GetValueOrDefault("n", 0) * 2)', 10),
    ('@(context.Request.Headers["Authorization"].First().Split(\' \').Last())', "a.b.c"),
    ('@(string.IsNullOrEmpty(context.Request.Headers.GetValueOrDefault("zz","")))', True),
    ("literal text", "literal text"),
]
for src, want in T:
    check(src[:70], E.evaluate(src, ENV), want)
for bad in ('@(new Foo())', '@(context.Nope)', '@(1 / 0)', '@(context.Request.Headers["missing"])'):
    try:
        E.evaluate(bad, ENV); ok = False
    except E.ExprError:
        ok = True
    check("ExprError: " + bad, ok, True)
print("RESULT fails=%d" % fails)
sys.exit(1 if fails else 0)
