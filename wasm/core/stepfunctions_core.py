"""AWS Step Functions core — substrate-independent state-machine service
(botocore `stepfunctions`, 2016-11-23, JSON protocol 1.0, X-Amz-Target `AWSStepFunctions.*`).

Speaks the native Step Functions wire so an unmodified aws-sdk-java-v2 / aws-sdk-go-v2 /
`aws stepfunctions` client works with only the endpoint changed. State machines are
**really executed**: an Amazon States Language interpreter runs Pass / Task / Choice /
Wait / Succeed / Fail / Parallel / Map states (Parameters, InputPath, ResultPath,
ResultSelector, OutputPath, Retry, Catch, intrinsic functions, JSONPath) and records the
full execution history. Task states call Lambda functions through `lambda_core`, or park
on an activity / `.waitForTaskToken` callback until SendTaskSuccess/Failure arrives.
Wait states complete instantly (the simulator does not sleep).

NO fastapi / boto3 / socket imports → loads under Pyodide. State lives on a plain store
object (`StepFunctionsStore`, public dict attrs) so nano_persist captures it like every
other store.
"""
from __future__ import annotations

import copy
import json
import re
import time
import uuid
from dataclasses import dataclass, field

REGION = "us-east-1"
ACCOUNT = "000000000000"
_JSON_CT = "application/x-amz-json-1.0"


class StepFunctionsStore:
    """Public dict attrs only → persisted/synced by core/nano_persist."""

    def __init__(self):
        self.machines: dict = {}      # name -> state machine record
        self.executions: dict = {}    # executionArn -> execution record
        self.activities: dict = {}    # activityArn -> activity record
        self.tokens: dict = {}        # taskToken -> {executionArn, activityArn|None, ...}
        self.tags: dict = {}          # resource arn -> {key: value}


_SHARED: StepFunctionsStore | None = None
# Live (non-persisted) execution generators awaiting a task token.
_RUNNING: dict = {}
# Lambda store override (the wire router passes its own); None → the store itself.
_LAMBDA_STORE = None


def shared_store() -> StepFunctionsStore:
    """The appliance-wide store: the native wire and the console REST share it."""
    global _SHARED
    if _SHARED is None:
        _SHARED = StepFunctionsStore()
    return _SHARED


def set_lambda_store(store) -> None:
    global _LAMBDA_STORE
    _LAMBDA_STORE = store


@dataclass
class SfnResponse:
    status: int = 200
    body: dict = field(default_factory=dict)
    headers: dict = field(default_factory=dict)


class _E(Exception):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def _dumps(o):
    return json.dumps(o, separators=(",", ":"))


def _now() -> float:
    return round(time.time(), 3)


def _iso(ts) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts)) if ts else ""


def _sm_arn(name): return f"arn:aws:states:{REGION}:{ACCOUNT}:stateMachine:{name}"
def _exec_arn(sm, name): return f"arn:aws:states:{REGION}:{ACCOUNT}:execution:{sm}:{name}"
def _act_arn(name): return f"arn:aws:states:{REGION}:{ACCOUNT}:activity:{name}"


_NAME_BAD = re.compile(r'[\s<>{}\[\]?*"#%\\^|~`$&,;:/\x00-\x1f\x7f-\x9f]')


def _check_name(name, what="name"):
    if not isinstance(name, str) or not 1 <= len(name) <= 80 or _NAME_BAD.search(name):
        raise _E("InvalidName", f"Invalid Name: '{name}' (does not match pattern for {what})")


def _parse_arn(arn, kind):
    """`arn:aws:states:r:a:<kind>:<name>[:<qualifier>]` -> (name, qualifier)."""
    parts = str(arn or "").split(":")
    if len(parts) < 7 or parts[0] != "arn" or parts[2] != "states" or parts[5] != kind:
        raise _E("InvalidArn", f"Invalid Arn: '{arn}'")
    return parts[6], (":".join(parts[7:]) or None)


def _tags_in(lst):
    return {str(t.get("key")): str(t.get("value", "")) for t in (lst or []) if isinstance(t, dict)}


def _tags_out(d):
    return [{"key": k, "value": v} for k, v in sorted((d or {}).items())]


# ═══════════════════════════════ ASL validation ═══════════════════════════════
_STATE_TYPES = {"Pass", "Task", "Choice", "Wait", "Succeed", "Fail", "Parallel", "Map"}


def _validate(defn, _path="$", top=True):
    """Returns a list of diagnostics ({severity, code, message, location})."""
    diags = []

    def err(code, msg, loc=_path):
        diags.append({"severity": "ERROR", "code": code, "message": msg, "location": loc})

    if not isinstance(defn, dict):
        err("INVALID_JSON_DESCRIPTION", "Definition must be a JSON object")
        return diags
    states = defn.get("States")
    if not isinstance(states, dict) or not states:
        err("MISSING_STATES", "The 'States' field is required and must be a non-empty object", _path)
        return diags
    start = defn.get("StartAt")
    if not start:
        err("MISSING_START_AT", "The 'StartAt' field is required", _path)
    elif start not in states:
        err("MISSING_TRANSITION_TARGET", f"StartAt refers to an undefined state: '{start}'", _path + ".StartAt")
    terminal = False
    for name, st in states.items():
        loc = f"{_path}.States.{name}"
        if not isinstance(st, dict) or st.get("Type") not in _STATE_TYPES:
            err("INVALID_STATE_TYPE", f"State '{name}' has an invalid or missing 'Type'", loc)
            continue
        t = st["Type"]
        if t in ("Succeed", "Fail"):
            terminal = True
        elif t == "Choice":
            for i, rule in enumerate(st.get("Choices") or []):
                nxt = rule.get("Next")
                if nxt not in states:
                    err("MISSING_TRANSITION_TARGET", f"Choice rule refers to an undefined state: '{nxt}'", f"{loc}.Choices[{i}]")
            if st.get("Default") and st["Default"] not in states:
                err("MISSING_TRANSITION_TARGET", f"Default refers to an undefined state: '{st['Default']}'", loc + ".Default")
            if not st.get("Choices"):
                err("MISSING_CHOICES", "Choice state requires a non-empty 'Choices' array", loc)
        else:
            if st.get("End") is True:
                terminal = True
            elif st.get("Next") not in states:
                err("MISSING_TRANSITION_TARGET",
                    f"State '{name}' must set End=true or a Next that refers to a defined state", loc)
            if t == "Task" and not st.get("Resource"):
                err("MISSING_RESOURCE", f"Task state '{name}' requires a 'Resource'", loc)
            if t == "Wait" and not any(k in st for k in ("Seconds", "SecondsPath", "Timestamp", "TimestampPath")):
                err("MISSING_WAIT_FIELD", f"Wait state '{name}' requires Seconds, SecondsPath, Timestamp or TimestampPath", loc)
            if t == "Parallel":
                for i, br in enumerate(st.get("Branches") or []):
                    diags.extend(_validate(br, f"{loc}.Branches[{i}]", False))
            if t == "Map":
                sub = st.get("ItemProcessor") or st.get("Iterator")
                if sub is None:
                    err("MISSING_ITEM_PROCESSOR", f"Map state '{name}' requires an ItemProcessor", loc)
                else:
                    diags.extend(_validate(sub, loc + ".ItemProcessor", False))
        for c in st.get("Catch") or []:
            if c.get("Next") not in states:
                err("MISSING_TRANSITION_TARGET", f"Catch refers to an undefined state: '{c.get('Next')}'", loc + ".Catch")
    if not terminal and states:
        err("NO_TERMINAL_STATE", "At least one state must be terminal (End=true, Succeed or Fail)", _path)
    return diags


def _parse_definition(text):
    try:
        defn = json.loads(text) if isinstance(text, str) else text
    except Exception as e:
        raise _E("InvalidDefinition", f"Invalid State Machine Definition: 'SCHEMA_VALIDATION_FAILED: {e}'")
    diags = _validate(defn)
    if diags:
        d = diags[0]
        raise _E("InvalidDefinition", f"Invalid State Machine Definition: '{d['code']}: {d['message']} at {d['location']}'")
    return defn


# ═══════════════════════════ JSONPath + intrinsics ════════════════════════════
_TOK = re.compile(r"\.([A-Za-z0-9_\-@]+)|\['([^']+)'\]|\[(\d+|\*)\]")


def _path_get(doc, path):
    if path is None:
        return doc
    if path == "$":
        return doc
    if not path.startswith("$"):
        raise _E("States.Runtime", f"Invalid path '{path}'")
    cur = [doc]
    pos = 1
    while pos < len(path):
        m = _TOK.match(path, pos)
        if not m:
            raise _E("States.Runtime", f"Invalid path '{path}'")
        pos = m.end()
        key, qkey, idx = m.groups()
        key = key or qkey
        nxt = []
        for c in cur:
            if key is not None:
                if isinstance(c, dict) and key in c:
                    nxt.append(c[key])
                else:
                    raise _E("States.Runtime", f"The JSONPath '{path}' could not be found in the input '{_dumps(doc)[:200]}'")
            elif idx == "*":
                if isinstance(c, list):
                    nxt.extend(c)
            else:
                i = int(idx)
                if isinstance(c, list) and i < len(c):
                    nxt.append(c[i])
                else:
                    raise _E("States.Runtime", f"The JSONPath '{path}' could not be found in the input")
        cur = nxt
    return cur[0] if "[*]" not in path else cur


def _path_set(doc, path, value):
    if path is None:
        return doc
    if path == "$":
        return value
    keys = [k or q for k, q, _ in (m.groups() for m in _TOK.finditer(path))]
    out = copy.deepcopy(doc) if isinstance(doc, dict) else {}
    cur = out
    for k in keys[:-1]:
        if not isinstance(cur.get(k), dict):
            cur[k] = {}
        cur = cur[k]
    cur[keys[-1]] = value
    return out


def _resolve(path, data, ctx):
    if path.startswith("$$"):
        return _path_get(ctx, path[1:])
    return _path_get(data, path)


def _split_args(s):
    args, depth, cur, q = [], 0, "", None
    for ch in s:
        if q:
            cur += ch
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
            cur += ch
        elif ch == "(":
            depth += 1
            cur += ch
        elif ch == ")":
            depth -= 1
            cur += ch
        elif ch == "," and depth == 0:
            args.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        args.append(cur.strip())
    return args


def _intrinsic(expr, data, ctx):
    expr = expr.strip()
    m = re.match(r"^States\.(\w+)\((.*)\)$", expr, re.S)
    if not m:
        if expr.startswith("'") and expr.endswith("'"):
            return expr[1:-1]
        if expr.startswith("$"):
            return _resolve(expr, data, ctx)
        try:
            return json.loads(expr)
        except Exception:
            raise _E("States.Runtime", f"Invalid intrinsic argument '{expr}'")
    fn, raw = m.group(1), m.group(2)
    args = [_intrinsic(a, data, ctx) for a in _split_args(raw)]
    if fn == "Format":
        s = str(args[0])
        for a in args[1:]:
            s = s.replace("{}", a if isinstance(a, str) else _dumps(a), 1)
        return s
    if fn == "JsonToString": return _dumps(args[0], separators=(",", ":"))
    if fn == "StringToJson": return json.loads(args[0])
    if fn == "Array": return list(args)
    if fn == "ArrayLength": return len(args[0])
    if fn == "ArrayContains": return args[1] in args[0]
    if fn == "ArrayGetItem": return args[0][int(args[1])]
    if fn == "ArrayUnique":
        out = []
        for a in args[0]:
            if a not in out:
                out.append(a)
        return out
    if fn == "ArrayRange": return list(range(int(args[0]), int(args[1]) + 1, int(args[2])))
    if fn == "ArrayPartition":
        n = int(args[1])
        return [args[0][i:i + n] for i in range(0, len(args[0]), n)]
    if fn == "MathAdd": return args[0] + args[1]
    if fn == "MathRandom": return int(args[0]) + (uuid.uuid4().int % max(1, int(args[1]) - int(args[0])))
    if fn == "StringSplit": return str(args[0]).split(str(args[1]))
    if fn == "UUID": return str(uuid.uuid4())
    if fn == "Hash":
        import hashlib
        return hashlib.new(str(args[1]).lower().replace("-", ""), (args[0] if isinstance(args[0], str) else _dumps(args[0])).encode()).hexdigest()
    if fn == "Base64Encode":
        import base64
        return base64.b64encode(str(args[0]).encode()).decode()
    if fn == "Base64Decode":
        import base64
        return base64.b64decode(str(args[0])).decode()
    if fn == "JsonMerge":
        return {**args[0], **args[1]}
    raise _E("States.Runtime", f"Unknown intrinsic function States.{fn}")


def _apply_template(tmpl, data, ctx):
    """Parameters / ResultSelector: keys ending `.$` are evaluated."""
    if isinstance(tmpl, dict):
        out = {}
        for k, v in tmpl.items():
            if k.endswith(".$") and isinstance(v, str):
                out[k[:-2]] = _intrinsic(v, data, ctx) if v.startswith("States.") else _resolve(v, data, ctx)
            else:
                out[k] = _apply_template(v, data, ctx)
        return out
    if isinstance(tmpl, list):
        return [_apply_template(v, data, ctx) for v in tmpl]
    return tmpl


# ═══════════════════════════════════ Choice ═══════════════════════════════════
_CMP = {
    "StringEquals": lambda a, b: a == b, "StringLessThan": lambda a, b: a < b,
    "StringGreaterThan": lambda a, b: a > b, "StringLessThanEquals": lambda a, b: a <= b,
    "StringGreaterThanEquals": lambda a, b: a >= b,
    "NumericEquals": lambda a, b: a == b, "NumericLessThan": lambda a, b: a < b,
    "NumericGreaterThan": lambda a, b: a > b, "NumericLessThanEquals": lambda a, b: a <= b,
    "NumericGreaterThanEquals": lambda a, b: a >= b,
    "BooleanEquals": lambda a, b: a is b,
    "TimestampEquals": lambda a, b: a == b, "TimestampLessThan": lambda a, b: a < b,
    "TimestampGreaterThan": lambda a, b: a > b, "TimestampLessThanEquals": lambda a, b: a <= b,
    "TimestampGreaterThanEquals": lambda a, b: a >= b,
}


def _like(s, pat):
    rx = ".*".join(re.escape(p) for p in pat.split("*"))
    return re.fullmatch(rx, s, re.S) is not None


def _eval_choice(rule, data, ctx):
    if "And" in rule: return all(_eval_choice(r, data, ctx) for r in rule["And"])
    if "Or" in rule: return any(_eval_choice(r, data, ctx) for r in rule["Or"])
    if "Not" in rule: return not _eval_choice(rule["Not"], data, ctx)
    var = rule.get("Variable")
    try:
        val = _resolve(var, data, ctx)
        present = True
    except _E:
        val, present = None, False
    for op, expected in rule.items():
        if op in ("Variable", "Next"):
            continue
        if op == "IsPresent": return present == expected
        if not present:
            return False
        if op == "IsNull": return (val is None) == expected
        if op == "IsString": return isinstance(val, str) == expected
        if op == "IsBoolean": return isinstance(val, bool) == expected
        if op == "IsNumeric": return (isinstance(val, (int, float)) and not isinstance(val, bool)) == expected
        if op == "IsTimestamp": return bool(isinstance(val, str) and re.match(r"^\d{4}-\d\d-\d\dT", val)) == expected
        if op == "StringMatches": return _like(str(val), expected)
        base, path = (op[:-4], True) if op.endswith("Path") else (op, False)
        fn = _CMP.get(base)
        if fn:
            exp = _resolve(expected, data, ctx) if path else expected
            try:
                return bool(fn(val, exp))
            except TypeError:
                return False
    return False


# ═══════════════════════════ execution interpreter ═══════════════════════════
class _Fail(Exception):
    def __init__(self, error, cause=""):
        super().__init__(error)
        self.error, self.cause = error, cause


class _Stop(Exception):
    """Execution was stopped/timed out while waiting."""


class _Run:
    """One execution's interpreter state. Generator-based so a Task can park on a
    task token (`yield token`) and resume when SendTask* delivers the result."""

    def __init__(self, store, ex, sm, lambda_store):
        self.store, self.ex, self.sm, self.lam = store, ex, sm, lambda_store
        self.history = ex["_history"]
        self.ctx = {"Execution": {"Id": ex["executionArn"], "Input": ex["_input_obj"], "Name": ex["name"],
                                  "RoleArn": sm["roleArn"], "StartTime": _iso8601(ex["startDate"])},
                    "StateMachine": {"Id": sm["stateMachineArn"], "Name": sm["name"]},
                    "State": {}, "Task": {}}

    def event(self, etype, prev=0, **details):
        eid = len(self.history) + 1
        ev = {"timestamp": _now(), "type": etype, "id": eid, "previousEventId": prev}
        ev.update(details)
        self.history.append(ev)
        return eid

    # -- core loop ---------------------------------------------------------
    def run_machine(self, defn, data, prev):
        states = defn["States"]
        name = defn["StartAt"]
        while True:
            st = states[name]
            data, nxt, prev = yield from self.run_state(name, st, states, data, prev)
            if nxt is None:
                return data, prev
            name = nxt

    def _io_in(self, st, data):
        d = _path_get(data, st.get("InputPath", "$")) if st.get("InputPath", "$") is not None else {}
        if "Parameters" in st:
            d = _apply_template(st["Parameters"], d, self.ctx)
        return d

    def _io_out(self, st, raw_input, result):
        if "ResultSelector" in st:
            result = _apply_template(st["ResultSelector"], result, self.ctx)
        rp = st.get("ResultPath", "$")
        d = raw_input if rp is None else _path_set(raw_input, rp, result)
        op = st.get("OutputPath", "$")
        return {} if op is None else _path_get(d, op)

    def run_state(self, name, st, states, data, prev):
        t = st["Type"]
        self.ctx["State"] = {"Name": name, "EnteredTime": _iso8601(_now())}
        entered = self.event(t + "StateEntered", prev, stateEnteredEventDetails={
            "name": name, "input": _dumps(data), "inputDetails": {"truncated": False}})
        nxt = st.get("Next")
        try:
            if t == "Succeed":
                out = _path_get(_path_get(data, st.get("InputPath", "$")), st.get("OutputPath", "$"))
                nxt = None
            elif t == "Fail":
                raise _Fail(st.get("Error", ""), st.get("Cause", ""))
            elif t == "Pass":
                d = self._io_in(st, data)
                out = self._io_out(st, data, st["Result"] if "Result" in st else d)
            elif t == "Wait":
                if "SecondsPath" in st:
                    _path_get(data, st["SecondsPath"])
                out = _path_get(data, st.get("OutputPath", "$"))
            elif t == "Choice":
                d = _path_get(data, st.get("InputPath", "$"))
                nxt = st.get("Default")
                for rule in st["Choices"]:
                    if _eval_choice(rule, d, self.ctx):
                        nxt = rule["Next"]
                        break
                if nxt is None:
                    raise _Fail("States.NoChoiceMatched", "An error occurred while executing the state '%s'. "
                                "No Choices matched and no Default was specified." % name)
                out = _path_get(d, st.get("OutputPath", "$"))
            elif t == "Task":
                out = yield from self._with_retry(name, st, data, entered, self._task)
            elif t == "Parallel":
                out = yield from self._with_retry(name, st, data, entered, self._parallel)
            elif t == "Map":
                out = yield from self._with_retry(name, st, data, entered, self._map)
            else:
                raise _Fail("States.Runtime", f"Unsupported state type {t}")
        except _Fail as f:
            catch = self._find_catch(st, f.error)
            if catch is None or t not in ("Task", "Parallel", "Map"):
                raise
            err_out = {"Error": f.error, "Cause": f.cause}
            rp = catch.get("ResultPath", "$")
            d = err_out if rp == "$" else _path_set(data, rp, err_out) if rp else data
            ex_id = self.event(t + "StateExited", entered, stateExitedEventDetails={
                "name": name, "output": _dumps(d), "outputDetails": {"truncated": False}})
            return d, catch["Next"], ex_id
        if st.get("End") or nxt is None:
            nxt = None
        exited = self.event(t + "StateExited", entered, stateExitedEventDetails={
            "name": name, "output": _dumps(out), "outputDetails": {"truncated": False}})
        return out, nxt, exited

    @staticmethod
    def _find_catch(st, error):
        for c in st.get("Catch") or []:
            errs = c.get("ErrorEquals") or []
            if "States.ALL" in errs or error in errs or (
                    "States.TaskFailed" in errs and not error.startswith("States.")):
                return c
        return None

    def _with_retry(self, name, st, data, entered, fn):
        attempts = {}
        while True:
            try:
                return (yield from fn(name, st, data, entered))
            except _Fail as f:
                hit = None
                for i, r in enumerate(st.get("Retry") or []):
                    errs = r.get("ErrorEquals") or []
                    if "States.ALL" in errs or f.error in errs or (
                            "States.TaskFailed" in errs and not f.error.startswith("States.")):
                        hit = (i, r)
                        break
                if hit is None or attempts.get(hit[0], 0) >= int(hit[1].get("MaxAttempts", 3)):
                    raise
                attempts[hit[0]] = attempts.get(hit[0], 0) + 1

    # -- Task --------------------------------------------------------------
    def _task(self, name, st, data, entered):
        res = st["Resource"]
        d = self._io_in(st, data)
        sched = self.event("TaskScheduled", entered, taskScheduledEventDetails={
            "resourceType": "lambda" if "lambda" in res else "activity", "resource": res,
            "region": REGION, "parameters": _dumps(d)})
        self.event("TaskStarted", sched, taskStartedEventDetails={
            "resourceType": "lambda" if "lambda" in res else "activity", "resource": res})
        wait_token = res.endswith(".waitForTaskToken")
        result = None
        try:
            if res.startswith("arn:aws:states:") and ":activity:" in res:
                if res not in self.store.activities:
                    raise _Fail("States.Runtime", f"Activity does not exist: {res}")
                token = self._new_token(activity=res, payload=d)
                result = yield ("token", token)
            elif res.startswith("arn:aws:states:::lambda:invoke"):
                fn_name = d.get("FunctionName", "")
                payload = d.get("Payload", {})
                if wait_token:
                    token = self._new_token(payload=payload)
                    if isinstance(payload, dict):
                        payload = dict(payload)
                    self._invoke_lambda(fn_name, payload, token)
                    result = yield ("token", token)
                else:
                    out = self._invoke_lambda(fn_name, payload)
                    result = {"ExecutedVersion": "$LATEST", "Payload": out, "SdkHttpMetadata": {"HttpStatusCode": 200},
                              "SdkResponseMetadata": {"RequestId": uuid.uuid4().hex}, "StatusCode": 200}
            elif res.startswith("arn:aws:lambda:"):
                result = self._invoke_lambda(res.split(":function:")[-1].split(":")[0], d)
            elif res.startswith("arn:aws:states:::"):
                raise _Fail("States.TaskFailed", f"Service integration '{res}' is not simulated by this appliance "
                            "(supported: lambda:invoke, lambda:invoke.waitForTaskToken, activities)")
            else:
                raise _Fail("States.Runtime", f"Invalid resource ARN: {res}")
        except _Fail as f:
            self.event("TaskFailed", sched, taskFailedEventDetails={
                "resourceType": "lambda", "resource": res, "error": f.error, "cause": f.cause})
            raise
        self.event("TaskSucceeded", sched, taskSucceededEventDetails={
            "resourceType": "lambda", "resource": res, "output": _dumps(result)})
        return self._io_out(st, data, result)

    def _new_token(self, activity=None, payload=None):
        token = uuid.uuid4().hex + uuid.uuid4().hex
        self.store.tokens[token] = {"executionArn": self.ex["executionArn"], "activityArn": activity,
                                    "input": _dumps(payload), "delivered": False}
        return token

    def _invoke_lambda(self, fn_name, payload, token=None):
        from core import lambda_core
        fn_name = fn_name.split(":function:")[-1].split(":")[0] if "arn:" in fn_name else fn_name
        store = self.lam if self.lam is not None else self.store
        if isinstance(payload, dict) and token:
            payload = dict(payload)
            payload["TaskToken"] = token
        out = lambda_core.dispatch(store, "POST", f"/2015-03-31/functions/{fn_name}/invocations", {}, {},
                                   _dumps(payload if payload is not None else {}).encode())
        if out.status == 404:
            raise _Fail("Lambda.ResourceNotFoundException",
                        f"Function not found: arn:aws:lambda:{REGION}:{ACCOUNT}:function:{fn_name}")
        try:
            val = json.loads(out.body.decode("utf-8")) if out.body else None
        except Exception:
            val = None
        if (out.headers or {}).get("X-Amz-Function-Error"):
            err = val if isinstance(val, dict) else {}
            raise _Fail(err.get("errorType", "Lambda.Unknown"), _dumps(err))
        return val

    # -- Parallel / Map ------------------------------------------------------
    def _parallel(self, name, st, data, entered):
        d = self._io_in(st, data)
        results = []
        for br in st["Branches"]:
            out, _ = yield from self.run_machine(br, d, entered)
            results.append(out)
        return self._io_out(st, data, results)

    def _map(self, name, st, data, entered):
        d = self._io_in(st, data)
        items = _path_get(d, st["ItemsPath"]) if st.get("ItemsPath") else d
        if not isinstance(items, list):
            raise _Fail("States.Runtime", "The ItemsPath did not reference an array")
        proc = st.get("ItemProcessor") or st["Iterator"]
        results = []
        for i, item in enumerate(items):
            sel = item
            if "ItemSelector" in st or "Parameters" in st:
                self.ctx["Map"] = {"Item": {"Index": i, "Value": item}}
                sel = _apply_template(st.get("ItemSelector") or st["Parameters"], d, self.ctx)
            out, _ = yield from self.run_machine(proc, sel, entered)
            results.append(out)
        return self._io_out({k: v for k, v in st.items() if k != "Parameters"}, data, results)


def _iso8601(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ts))


def _finish(store, ex, status, output=None, error=None, cause=None):
    ex["status"] = status
    ex["stopDate"] = _now()
    if output is not None:
        ex["output"] = output if isinstance(output, str) else _dumps(output)
    if error is not None:
        ex["error"] = error
    if cause is not None:
        ex["cause"] = cause
    _RUNNING.pop(ex["executionArn"], None)
    for tok in [t for t, v in store.tokens.items() if v["executionArn"] == ex["executionArn"]]:
        store.tokens.pop(tok, None)


def _step(store, ex, gen, send=None, throw=None):
    """Advance an execution until it finishes or parks on a token."""
    h = ex["_history"]
    try:
        r = gen.throw(throw) if throw is not None else gen.send(send)
        ex["_waiting"] = r[1]
        _RUNNING[ex["executionArn"]] = gen
        return
    except StopIteration as done:
        out, prev = done.value
        h.append({"timestamp": _now(), "type": "ExecutionSucceeded", "id": len(h) + 1, "previousEventId": prev,
                  "executionSucceededEventDetails": {"output": _dumps(out), "outputDetails": {"truncated": False}}})
        _finish(store, ex, "SUCCEEDED", output=out)
    except _Fail as f:
        h.append({"timestamp": _now(), "type": "ExecutionFailed", "id": len(h) + 1, "previousEventId": 0,
                  "executionFailedEventDetails": {"error": f.error, "cause": f.cause}})
        _finish(store, ex, "FAILED", error=f.error, cause=f.cause)
    except _E as e:
        h.append({"timestamp": _now(), "type": "ExecutionFailed", "id": len(h) + 1, "previousEventId": 0,
                  "executionFailedEventDetails": {"error": e.code, "cause": e.message}})
        _finish(store, ex, "FAILED", error=e.code, cause=e.message)
    ex.pop("_waiting", None)


def _start(store, sm, name, input_text, lambda_store):
    try:
        inp = json.loads(input_text) if input_text not in (None, "") else {}
    except Exception:
        raise _E("InvalidExecutionInput", "Invalid State Machine Execution Input: 'Unrecognized token'")
    arn = _exec_arn(sm["name"], name)
    ex = {"executionArn": arn, "stateMachineArn": sm["stateMachineArn"], "name": name, "status": "RUNNING",
          "startDate": _now(), "input": input_text if input_text not in (None, "") else "{}",
          "_input_obj": inp, "_history": [], "redriveCount": 0, "definition": sm["definition"],
          "roleArn": sm["roleArn"], "type": sm["type"]}
    store.executions[arn] = ex
    ex["_history"].append({"timestamp": ex["startDate"], "type": "ExecutionStarted", "id": 1, "previousEventId": 0,
                           "executionStartedEventDetails": {"input": ex["input"], "inputDetails": {"truncated": False},
                                                            "roleArn": sm["roleArn"]}})
    run = _Run(store, ex, sm, lambda_store)
    defn = json.loads(sm["definition"])
    gen = run.run_machine(defn, inp, 1)
    _step(store, ex, gen)
    return ex


# ══════════════════════════════════ operations ══════════════════════════════════
def _machine(store, arn):
    name, _q = _parse_arn(arn, "stateMachine")
    sm = store.machines.get(name)
    if not sm:
        raise _E("StateMachineDoesNotExist", f"State Machine Does Not Exist: '{arn}'")
    return sm


def _resolve_sm(store, arn):
    """ARN of a state machine, version or alias -> (machine, definition-record)."""
    name, q = _parse_arn(arn, "stateMachine")
    sm = store.machines.get(name)
    if not sm:
        raise _E("StateMachineDoesNotExist", f"State Machine Does Not Exist: '{arn}'")
    if q is None:
        return sm
    if q.isdigit():
        v = sm["versions"].get(q)
        if not v:
            raise _E("StateMachineDoesNotExist", f"State Machine Does Not Exist: '{arn}'")
        return dict(sm, **{k: v[k] for k in ("definition", "roleArn")})
    al = sm["aliases"].get(q)
    if not al:
        raise _E("StateMachineDoesNotExist", f"State Machine Does Not Exist: '{arn}'")
    ver = al["routingConfiguration"][0]["stateMachineVersionArn"]
    return _resolve_sm(store, ver)


def _sm_summary(sm):
    return {"stateMachineArn": sm["stateMachineArn"], "name": sm["name"], "type": sm["type"],
            "creationDate": sm["creationDate"]}


def _paginate(items, body, key, default=100):
    limit = int(body.get("maxResults") or default)
    start = int(body.get("nextToken") or 0)
    page = items[start:start + limit]
    out = {key: page}
    if start + limit < len(items):
        out["nextToken"] = str(start + limit)
    return out


def op_create_state_machine(store, b):
    name = b.get("name")
    _check_name(name)
    if not b.get("definition"):
        raise _E("ValidationException", "1 validation error detected: Value null at 'definition' failed to satisfy constraint")
    if not b.get("roleArn"):
        raise _E("MissingRequiredParameter", "Missing required parameter: roleArn")
    if not str(b["roleArn"]).startswith("arn:"):
        raise _E("InvalidArn", f"Invalid Arn: '{b['roleArn']}'")
    typ = b.get("type") or "STANDARD"
    if typ not in ("STANDARD", "EXPRESS"):
        raise _E("ValidationException", f"Value '{typ}' at 'type' failed to satisfy constraint")
    _parse_definition(b["definition"])
    old = store.machines.get(name)
    if old:
        if old["definition"] == b["definition"] and old["roleArn"] == b["roleArn"] and old["type"] == typ:
            return {"stateMachineArn": old["stateMachineArn"], "creationDate": old["creationDate"]}
        raise _E("StateMachineAlreadyExists", f"State Machine Already Exists: '{old['stateMachineArn']}'")
    sm = {"stateMachineArn": _sm_arn(name), "name": name, "status": "ACTIVE", "definition": b["definition"],
          "roleArn": b["roleArn"], "type": typ, "creationDate": _now(),
          "loggingConfiguration": b.get("loggingConfiguration") or {"level": "OFF", "includeExecutionData": False, "destinations": []},
          "tracingConfiguration": b.get("tracingConfiguration") or {"enabled": False},
          "revisionId": uuid.uuid4().hex, "description": "", "versions": {}, "aliases": {}, "nextVersion": 1}
    store.machines[name] = sm
    store.tags[sm["stateMachineArn"]] = _tags_in(b.get("tags"))
    out = {"stateMachineArn": sm["stateMachineArn"], "creationDate": sm["creationDate"]}
    if b.get("publish"):
        out["stateMachineVersionArn"] = _publish(sm, b.get("versionDescription"))["stateMachineVersionArn"]
    return out


def _publish(sm, desc=None):
    n = sm["nextVersion"]
    sm["nextVersion"] += 1
    v = {"stateMachineVersionArn": f"{sm['stateMachineArn']}:{n}", "creationDate": _now(), "description": desc or "",
         "definition": sm["definition"], "roleArn": sm["roleArn"], "revisionId": sm["revisionId"]}
    sm["versions"][str(n)] = v
    return v


def op_describe_state_machine(store, b):
    sm = _resolve_sm(store, b.get("stateMachineArn"))
    out = {k: sm[k] for k in ("stateMachineArn", "name", "status", "definition", "roleArn", "type", "creationDate",
                              "loggingConfiguration", "tracingConfiguration", "revisionId")}
    out["description"] = sm.get("description", "")
    return out


def op_update_state_machine(store, b):
    sm = _machine(store, b.get("stateMachineArn"))
    if not any(k in b for k in ("definition", "roleArn", "loggingConfiguration", "tracingConfiguration")):
        raise _E("MissingRequiredParameter", "Either the definition, the role ARN, the LoggingConfiguration, the "
                 "EncryptionConfiguration or the TracingConfiguration must be specified")
    if "definition" in b:
        _parse_definition(b["definition"])
        sm["definition"] = b["definition"]
    for k in ("roleArn", "loggingConfiguration", "tracingConfiguration"):
        if b.get(k):
            sm[k] = b[k]
    sm["revisionId"] = uuid.uuid4().hex
    out = {"updateDate": _now(), "revisionId": sm["revisionId"]}
    if b.get("publish"):
        out["stateMachineVersionArn"] = _publish(sm, b.get("versionDescription"))["stateMachineVersionArn"]
    return out


def op_delete_state_machine(store, b):
    sm = _machine(store, b.get("stateMachineArn"))
    del store.machines[sm["name"]]
    store.tags.pop(sm["stateMachineArn"], None)
    return {}


def op_list_state_machines(store, b):
    ms = sorted(store.machines.values(), key=lambda m: (m["creationDate"], m["name"]))
    return _paginate([_sm_summary(m) for m in ms], b, "stateMachines")


def op_publish_version(store, b):
    sm = _machine(store, b.get("stateMachineArn"))
    if b.get("revisionId") and b["revisionId"] != sm["revisionId"]:
        raise _E("ConflictException", "Failed to publish the state machine version: the revisionId does not match the current revision")
    v = _publish(sm, b.get("description"))
    return {"creationDate": v["creationDate"], "stateMachineVersionArn": v["stateMachineVersionArn"]}


def op_list_versions(store, b):
    sm = _machine(store, b.get("stateMachineArn"))
    vs = sorted(sm["versions"].values(), key=lambda v: -int(v["stateMachineVersionArn"].rsplit(":", 1)[1]))
    return _paginate([{"stateMachineVersionArn": v["stateMachineVersionArn"], "creationDate": v["creationDate"]} for v in vs],
                     b, "stateMachineVersions")


def op_delete_version(store, b):
    name, q = _parse_arn(b.get("stateMachineVersionArn"), "stateMachine")
    sm = store.machines.get(name)
    if sm and q in sm["versions"]:
        del sm["versions"][q]
    return {}


def _alias_arn(sm, name): return f"{sm['stateMachineArn']}:{name}"


def _check_routing(store, sm, rc):
    if not isinstance(rc, list) or not 1 <= len(rc) <= 2 or sum(int(r.get("weight", 0)) for r in rc) != 100:
        raise _E("ValidationException", "Invalid routingConfiguration: weights must total 100")
    for r in rc:
        n, q = _parse_arn(r.get("stateMachineVersionArn"), "stateMachine")
        if n != sm["name"] or q not in sm["versions"]:
            raise _E("ResourceNotFound", f"Version not found: {r.get('stateMachineVersionArn')}")


def op_create_alias(store, b):
    rc = b.get("routingConfiguration")
    if not rc:
        raise _E("MissingRequiredParameter", "Missing required parameter: routingConfiguration")
    name0, _ = _parse_arn(rc[0].get("stateMachineVersionArn"), "stateMachine")
    sm = store.machines.get(name0)
    if not sm:
        raise _E("ResourceNotFound", f"State machine not found: {name0}")
    _check_name(b.get("name"))
    _check_routing(store, sm, rc)
    if b["name"] in sm["aliases"]:
        raise _E("ConflictException", f"Alias already exists: {b['name']}")
    al = {"stateMachineAliasArn": _alias_arn(sm, b["name"]), "name": b["name"], "description": b.get("description", ""),
          "routingConfiguration": rc, "creationDate": _now(), "updateDate": _now()}
    sm["aliases"][b["name"]] = al
    return {"stateMachineAliasArn": al["stateMachineAliasArn"], "creationDate": al["creationDate"]}


def _alias(store, arn):
    name, q = _parse_arn(arn, "stateMachine")
    sm = store.machines.get(name)
    if not sm or not q or q not in sm["aliases"]:
        raise _E("ResourceNotFound", f"Alias not found: {arn}")
    return sm, sm["aliases"][q]


def op_describe_alias(store, b):
    _, al = _alias(store, b.get("stateMachineAliasArn"))
    return {k: al[k] for k in ("stateMachineAliasArn", "name", "description", "routingConfiguration", "creationDate", "updateDate")}


def op_update_alias(store, b):
    sm, al = _alias(store, b.get("stateMachineAliasArn"))
    if "routingConfiguration" in b:
        _check_routing(store, sm, b["routingConfiguration"])
        al["routingConfiguration"] = b["routingConfiguration"]
    if "description" in b:
        al["description"] = b["description"]
    al["updateDate"] = _now()
    return {"updateDate": al["updateDate"]}


def op_delete_alias(store, b):
    sm, al = _alias(store, b.get("stateMachineAliasArn"))
    del sm["aliases"][al["name"]]
    return {}


def op_list_aliases(store, b):
    sm = _machine(store, b.get("stateMachineArn"))
    als = sorted(sm["aliases"].values(), key=lambda a: a["creationDate"])
    return _paginate([{"stateMachineAliasArn": a["stateMachineAliasArn"], "creationDate": a["creationDate"]} for a in als],
                     b, "stateMachineAliases")


def _ex_name(b):
    name = b.get("name") or str(uuid.uuid4())
    _check_name(name)
    return name


def op_start_execution(store, b):
    sm = _resolve_sm(store, b.get("stateMachineArn"))
    name = _ex_name(b)
    arn = _exec_arn(sm["name"], name)
    prior = store.executions.get(arn)
    if prior:
        if prior["status"] == "RUNNING" and prior["input"] == (b.get("input") or "{}"):
            return {"executionArn": arn, "startDate": prior["startDate"]}
        raise _E("ExecutionAlreadyExists", f"Execution Already Exists: '{arn}'")
    ex = _start(store, sm, name, b.get("input"), _LAMBDA_STORE)
    return {"executionArn": ex["executionArn"], "startDate": ex["startDate"]}


def op_start_sync_execution(store, b):
    sm = _resolve_sm(store, b.get("stateMachineArn"))
    if sm["type"] != "EXPRESS":
        raise _E("StateMachineTypeNotSupported", "This operation is not supported by this type of state machine")
    ex = _start(store, sm, _ex_name(b), b.get("input"), _LAMBDA_STORE)
    out = {"executionArn": ex["executionArn"], "stateMachineArn": ex["stateMachineArn"], "name": ex["name"],
           "startDate": ex["startDate"], "stopDate": ex.get("stopDate") or _now(), "input": ex["input"],
           "inputDetails": {"included": True}, "status": ex["status"] if ex["status"] != "RUNNING" else "TIMED_OUT",
           "billingDetails": {"billedMemoryUsedInMB": 64, "billedDurationInMilliseconds": 100}}
    for k in ("output", "error", "cause"):
        if k in ex:
            out[k] = ex[k]
    if "output" in ex:
        out["outputDetails"] = {"included": True}
    return out


def _exec(store, arn):
    _parse_arn_exec(arn)
    ex = store.executions.get(arn)
    if not ex:
        raise _E("ExecutionDoesNotExist", f"Execution Does Not Exist: '{arn}'")
    return ex


def _parse_arn_exec(arn):
    _parse_arn(arn, "execution")


def _ex_view(ex, full=True):
    out = {"executionArn": ex["executionArn"], "stateMachineArn": ex["stateMachineArn"], "name": ex["name"],
           "status": ex["status"], "startDate": ex["startDate"]}
    if ex.get("stopDate"):
        out["stopDate"] = ex["stopDate"]
    if full:
        out["input"] = ex["input"]
        out["inputDetails"] = {"included": True}
        if "output" in ex:
            out["output"] = ex["output"]
            out["outputDetails"] = {"included": True}
        for k in ("error", "cause"):
            if k in ex:
                out[k] = ex[k]
        if ex.get("redriveCount"):
            out["redriveCount"] = ex["redriveCount"]
            out["redriveStatus"] = "REDRIVABLE"
        else:
            out["redriveStatus"] = "REDRIVABLE" if ex["status"] in ("FAILED", "TIMED_OUT", "ABORTED") else "NOT_REDRIVABLE"
    return out


def op_describe_execution(store, b):
    return _ex_view(_exec(store, b.get("executionArn")))


def op_stop_execution(store, b):
    ex = _exec(store, b.get("executionArn"))
    if ex["status"] == "RUNNING":
        gen = _RUNNING.pop(ex["executionArn"], None)
        if gen is not None:
            gen.close()
        h = ex["_history"]
        h.append({"timestamp": _now(), "type": "ExecutionAborted", "id": len(h) + 1, "previousEventId": 0,
                  "executionAbortedEventDetails": {k: b[k] for k in ("error", "cause") if b.get(k)}})
        _finish(store, ex, "ABORTED", error=b.get("error"), cause=b.get("cause"))
    return {"stopDate": ex.get("stopDate") or _now()}


def op_list_executions(store, b):
    arn = b.get("stateMachineArn")
    items = list(store.executions.values())
    if arn:
        sm = _machine(store, arn)
        items = [e for e in items if e["stateMachineArn"] == sm["stateMachineArn"]]
    elif not b.get("mapRunArn"):
        raise _E("ValidationException", "Either stateMachineArn or mapRunArn is required")
    sf = b.get("statusFilter")
    if sf:
        items = [e for e in items if e["status"] == sf]
    items.sort(key=lambda e: (-e["startDate"], e["name"]))
    return _paginate([_ex_view(e, False) for e in items], b, "executions")


def op_get_execution_history(store, b):
    ex = _exec(store, b.get("executionArn"))
    evs = list(ex["_history"])
    if b.get("reverseOrder"):
        evs.reverse()
    return _paginate(evs, b, "events", 100)


def op_describe_sm_for_execution(store, b):
    ex = _exec(store, b.get("executionArn"))
    sm = store.machines.get(_parse_arn(ex["stateMachineArn"], "stateMachine")[0]) or {}
    return {"stateMachineArn": ex["stateMachineArn"], "name": sm.get("name", ""), "definition": ex["definition"],
            "roleArn": ex["roleArn"], "updateDate": sm.get("creationDate", ex["startDate"]),
            "loggingConfiguration": sm.get("loggingConfiguration") or {"level": "OFF", "includeExecutionData": False},
            "tracingConfiguration": sm.get("tracingConfiguration") or {"enabled": False},
            "revisionId": sm.get("revisionId", "")}


def op_redrive(store, b):
    ex = _exec(store, b.get("executionArn"))
    if ex["status"] not in ("FAILED", "TIMED_OUT", "ABORTED"):
        raise _E("ExecutionNotRedrivable", f"Execution is not redrivable: status is {ex['status']}")
    sm = _machine(store, ex["stateMachineArn"])
    for k in ("output", "error", "cause", "stopDate"):
        ex.pop(k, None)
    ex["status"], ex["redriveCount"] = "RUNNING", ex.get("redriveCount", 0) + 1
    ex["_history"].append({"timestamp": _now(), "type": "ExecutionRedriven", "id": len(ex["_history"]) + 1,
                           "previousEventId": 0, "executionRedrivenEventDetails": {"redriveCount": ex["redriveCount"]}})
    run = _Run(store, ex, sm, _LAMBDA_STORE)
    _step(store, ex, run.run_machine(json.loads(ex["definition"]), ex["_input_obj"], len(ex["_history"])))
    return {"redriveDate": _now()}


# activities & callbacks
def op_create_activity(store, b):
    _check_name(b.get("name"))
    arn = _act_arn(b["name"])
    if arn in store.activities:
        return {"activityArn": arn, "creationDate": store.activities[arn]["creationDate"]}
    store.activities[arn] = {"activityArn": arn, "name": b["name"], "creationDate": _now(), "queue": []}
    store.tags[arn] = _tags_in(b.get("tags"))
    return {"activityArn": arn, "creationDate": store.activities[arn]["creationDate"]}


def _activity(store, arn):
    _parse_arn(arn, "activity")
    a = store.activities.get(arn)
    if not a:
        raise _E("ActivityDoesNotExist", f"Activity Does Not Exist: '{arn}'")
    return a


def op_describe_activity(store, b):
    a = _activity(store, b.get("activityArn"))
    return {"activityArn": a["activityArn"], "name": a["name"], "creationDate": a["creationDate"]}


def op_list_activities(store, b):
    acts = sorted(store.activities.values(), key=lambda a: (a["creationDate"], a["name"]))
    return _paginate([{"activityArn": a["activityArn"], "name": a["name"], "creationDate": a["creationDate"]} for a in acts],
                     b, "activities")


def op_delete_activity(store, b):
    a = _activity(store, b.get("activityArn"))
    del store.activities[a["activityArn"]]
    store.tags.pop(a["activityArn"], None)
    return {}


def op_get_activity_task(store, b):
    _activity(store, b.get("activityArn"))
    for token, t in store.tokens.items():
        if t.get("activityArn") == b["activityArn"] and not t["delivered"]:
            t["delivered"] = True
            return {"taskToken": token, "input": t["input"]}
    return {}


def _token(store, tok):
    t = store.tokens.get(tok)
    if not t:
        raise _E("TaskDoesNotExist", "Task Does Not Exist")
    return t


def op_send_success(store, b):
    t = _token(store, b.get("taskToken"))
    try:
        out = json.loads(b.get("output") or "null")
    except Exception:
        raise _E("InvalidOutput", "Invalid Output: 'Unrecognized token'")
    ex = store.executions[t["executionArn"]]
    store.tokens.pop(b["taskToken"], None)
    _step(store, ex, _RUNNING.get(ex["executionArn"]), send=out)
    return {}


def op_send_failure(store, b):
    t = _token(store, b.get("taskToken"))
    ex = store.executions[t["executionArn"]]
    store.tokens.pop(b["taskToken"], None)
    _step(store, ex, _RUNNING.get(ex["executionArn"]), throw=_Fail(b.get("error") or "", b.get("cause") or ""))
    return {}


def op_send_heartbeat(store, b):
    _token(store, b.get("taskToken"))
    return {}


# tags
def _tag_target(store, arn):
    parts = str(arn or "").split(":")
    if len(parts) < 7 or parts[2] != "states" or parts[5] not in ("stateMachine", "activity"):
        raise _E("InvalidArn", f"Invalid Arn: '{arn}'")
    base = ":".join(parts[:7])
    if base not in store.tags:
        raise _E("ResourceNotFound", f"Resource not found: '{arn}'")
    return base


def op_tag_resource(store, b):
    store.tags[_tag_target(store, b.get("resourceArn"))].update(_tags_in(b.get("tags")))
    return {}


def op_untag_resource(store, b):
    d = store.tags[_tag_target(store, b.get("resourceArn"))]
    for k in b.get("tagKeys") or []:
        d.pop(k, None)
    return {}


def op_list_tags(store, b):
    return {"tags": _tags_out(store.tags[_tag_target(store, b.get("resourceArn"))])}


# map runs (Distributed Map is not simulated: none are ever started)
def op_list_map_runs(store, b):
    _exec(store, b.get("executionArn"))
    return {"mapRuns": []}


def op_describe_map_run(store, b):
    raise _E("ResourceNotFound", f"Map Run Does Not Exist: '{b.get('mapRunArn')}'")


def op_update_map_run(store, b):
    raise _E("ResourceNotFound", f"Map Run Does Not Exist: '{b.get('mapRunArn')}'")


# validation + TestState
def op_validate(store, b):
    try:
        defn = json.loads(b.get("definition") or "")
    except Exception as e:
        return {"result": "FAIL", "diagnostics": [{"severity": "ERROR", "code": "INVALID_JSON_DESCRIPTION",
                                                    "message": f"JSON syntax error: {e}", "location": "$"}], "truncated": False}
    diags = _validate(defn)
    return {"result": "FAIL" if diags else "OK", "diagnostics": diags[: int(b.get("maxResults") or 100)], "truncated": False}


def op_test_state(store, b):
    try:
        st = json.loads(b.get("definition") or "")
    except Exception:
        raise _E("InvalidDefinition", "Invalid State Machine Definition: 'INVALID_JSON_DESCRIPTION'")
    if not isinstance(st, dict) or st.get("Type") not in _STATE_TYPES:
        raise _E("InvalidDefinition", "Invalid State Machine Definition: 'INVALID_STATE_TYPE'")
    try:
        data = json.loads(b.get("input") or "{}")
    except Exception:
        raise _E("InvalidExecutionInput", "Invalid State Machine Execution Input: 'Unrecognized token'")
    ex = {"executionArn": _exec_arn("test", "test"), "name": "test", "startDate": _now(), "_history": [], "_input_obj": data}
    run = _Run(store, ex, {"roleArn": b.get("roleArn", ""), "stateMachineArn": _sm_arn("test"), "name": "test"}, _LAMBDA_STORE)
    states = {"S": dict(st, End=True) if st["Type"] not in ("Choice", "Succeed", "Fail") and "Next" not in st else st}
    out = {}
    try:
        gen = run.run_state("S", states["S"], states, data, 0)
        try:
            next(gen)
            raise _Fail("States.Runtime", "TestState does not support callback/activity tasks")
        except StopIteration as done:
            res, nxt, _ = done.value
        out = {"output": _dumps(res), "status": "SUCCEEDED"}
        if nxt:
            out["nextState"] = nxt
        if b.get("inspectionLevel") in ("DEBUG", "TRACE"):
            out["inspectionData"] = {"input": _dumps(data), "result": _dumps(res)}
    except _Fail as f:
        out = {"error": f.error, "cause": f.cause, "status": "FAILED"}
        if run._find_catch(st, f.error):
            out["status"] = "CAUGHT_ERROR"
            out["nextState"] = run._find_catch(st, f.error)["Next"]
        elif any(f.error in (r.get("ErrorEquals") or []) or "States.ALL" in (r.get("ErrorEquals") or [])
                 for r in st.get("Retry") or []):
            out["status"] = "RETRIABLE"
    return out


_OPS = {
    "CreateStateMachine": op_create_state_machine, "DescribeStateMachine": op_describe_state_machine,
    "UpdateStateMachine": op_update_state_machine, "DeleteStateMachine": op_delete_state_machine,
    "ListStateMachines": op_list_state_machines, "PublishStateMachineVersion": op_publish_version,
    "ListStateMachineVersions": op_list_versions, "DeleteStateMachineVersion": op_delete_version,
    "CreateStateMachineAlias": op_create_alias, "DescribeStateMachineAlias": op_describe_alias,
    "UpdateStateMachineAlias": op_update_alias, "DeleteStateMachineAlias": op_delete_alias,
    "ListStateMachineAliases": op_list_aliases,
    "StartExecution": op_start_execution, "StartSyncExecution": op_start_sync_execution,
    "DescribeExecution": op_describe_execution, "StopExecution": op_stop_execution,
    "ListExecutions": op_list_executions, "GetExecutionHistory": op_get_execution_history,
    "DescribeStateMachineForExecution": op_describe_sm_for_execution, "RedriveExecution": op_redrive,
    "CreateActivity": op_create_activity, "DescribeActivity": op_describe_activity,
    "ListActivities": op_list_activities, "DeleteActivity": op_delete_activity,
    "GetActivityTask": op_get_activity_task, "SendTaskSuccess": op_send_success,
    "SendTaskFailure": op_send_failure, "SendTaskHeartbeat": op_send_heartbeat,
    "TagResource": op_tag_resource, "UntagResource": op_untag_resource, "ListTagsForResource": op_list_tags,
    "ListMapRuns": op_list_map_runs, "DescribeMapRun": op_describe_map_run, "UpdateMapRun": op_update_map_run,
    "ValidateStateMachineDefinition": op_validate, "TestState": op_test_state,
}


def dispatch(store, target: str, payload: dict | None = None, lambda_store=None) -> SfnResponse:
    """Native Step Functions JSON router. `target` is the X-Amz-Target header,
    e.g. "AWSStepFunctions.CreateStateMachine". `lambda_store` is the Lambda function
    registry Task states invoke (the wire router's / console adapter's own)."""
    global _LAMBDA_STORE
    if lambda_store is not None:
        _LAMBDA_STORE = lambda_store
    body = payload if isinstance(payload, dict) else {}
    action = target.rsplit(".", 1)[-1] if target else ""
    op = _OPS.get(action)
    if op is None:
        return SfnResponse(status=400, body={"__type": "com.amazon.coral.service#UnknownOperationException",
                                              "message": f"Unknown operation {action}."})
    try:
        return SfnResponse(body=op(store, body))
    except _E as e:
        return SfnResponse(status=e.status, body={"__type": e.code, "message": e.message},
                           headers={"x-amzn-ErrorType": e.code})


# ═══════════════════════════════ console views ═══════════════════════════════
def machine_view(sm, store=None) -> dict:
    """Console grid/detail row for a state machine — every grid column populated."""
    execs = [e for e in (store.executions.values() if store else []) if e["stateMachineArn"] == sm["stateMachineArn"]]
    states = len(json.loads(sm["definition"]).get("States", {}))
    last = max((e["startDate"] for e in execs), default=None)
    return {"id": sm["name"], "name": sm["name"], "arn": sm["stateMachineArn"], "type": sm["type"],
            "status": sm["status"], "role_arn": sm["roleArn"], "created": _iso(sm["creationDate"]),
            "state_count": states, "execution_count": len(execs),
            "running_count": sum(1 for e in execs if e["status"] == "RUNNING"),
            "last_execution": _iso(last) if last else "No executions yet",
            "version_count": len(sm["versions"]), "alias_count": len(sm["aliases"]),
            "logging_level": (sm.get("loggingConfiguration") or {}).get("level", "OFF"),
            "tracing_enabled": bool((sm.get("tracingConfiguration") or {}).get("enabled")),
            "revision_id": sm["revisionId"], "description": sm.get("description") or "",
            "definition": sm["definition"], "tags": dict(shared_tags(store, sm["stateMachineArn"]))}


def shared_tags(store, arn):
    return (store.tags.get(arn) if store else None) or {}


def execution_view(ex) -> dict:
    return {"id": ex["name"], "name": ex["name"], "arn": ex["executionArn"], "status": ex["status"],
            "started": _iso(ex["startDate"]), "stopped": _iso(ex.get("stopDate")) if ex.get("stopDate") else "Running",
            "input": ex["input"], "output": ex.get("output", ""), "error": ex.get("error", ""),
            "state_machine_arn": ex["stateMachineArn"]}


def default_role_arn() -> str:
    return f"arn:aws:iam::{ACCOUNT}:role/service-role/StepFunctions-ExecutionRole"


def default_definition() -> str:
    return json.dumps({"Comment": "A Hello World example of the Amazon States Language using Pass states",
                       "StartAt": "Hello", "States": {
                           "Hello": {"Type": "Pass", "Result": "Hello", "Next": "World"},
                           "World": {"Type": "Pass", "Result": "World", "End": True}}}, indent=2)


def children(store, sm, kind) -> dict:
    """Console detail-tab rows for a state machine: {items: [...]}; every cell populated."""
    if kind == "executions":
        rows = [execution_view(e) for e in store.executions.values() if e["stateMachineArn"] == sm["stateMachineArn"]]
        rows.sort(key=lambda r: r["started"], reverse=True)
        for r in rows:
            r["output"] = r["output"] or ("(none yet)" if r["status"] == "RUNNING" else "(none)")
            r["error"] = r["error"] or "(none)"
        return {"items": rows}
    if kind == "versions":
        return {"items": [{"version": q, "arn": v["stateMachineVersionArn"], "created": _iso(v["creationDate"]),
                           "description": v.get("description") or "(none)"}
                          for q, v in sorted(sm["versions"].items(), key=lambda kv: -int(kv[0]))]}
    if kind == "aliases":
        return {"items": [{"name": a["name"], "arn": a["stateMachineAliasArn"],
                           "routing": ", ".join(f"{r['stateMachineVersionArn'].rsplit(':', 1)[1]}:{r['weight']}%"
                                                for r in a["routingConfiguration"]),
                           "created": _iso(a["creationDate"])} for a in sm["aliases"].values()]}
    if kind == "activities":
        return {"items": [{"name": a["name"], "arn": a["activityArn"], "created": _iso(a["creationDate"])}
                          for a in store.activities.values()]}
    return {"items": []}
