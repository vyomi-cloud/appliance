from botocore.exceptions import ClientError

import vymodels
from chaos import inject

rt = vymodels._rt

# 1. Transient throttling: two refusals, then success.
f = inject(rt, "Converse", times=2)
reply = vymodels.chat("Reply with the single word OK.")
f["remove"]()
assert reply.strip() and f["seen"] == 3, "expected 3 attempts (2 throttled + 1 ok), saw %d" % f["seen"]
print("transient throttling: recovered after", f["seen"], "attempts")

# 2. Permanent throttling: the client must give up after MAX_ATTEMPTS with a clear error.
f = inject(rt, "Converse", times=99)
try:
    vymodels.chat("Reply with the single word OK.")
    raise AssertionError("a model that always throttles must not return an answer")
except vymodels.ModelUnavailable as e:
    print("permanent throttling: gave up cleanly ->", e)
assert f["seen"] == vymodels.MAX_ATTEMPTS, "must stop after exactly MAX_ATTEMPTS attempts, saw %d" % f["seen"]
f["remove"]()

# 3. A non-retryable error must NOT be retried (retrying a bad request only burns budget).
f = inject(rt, "Converse", times=99, status=400, code="ValidationException", message="bad request")
try:
    vymodels.chat("hello")
    raise AssertionError("a ValidationException must surface")
except Exception as e:
    assert isinstance(e, ClientError) and f["seen"] == 1, "validation errors must fail on the first attempt"
f["remove"]()
print("validation error: failed fast after", 1, "attempt")

# 4. The budget refuses before the call is made.
old = vymodels.BUDGET
vymodels.BUDGET = vymodels.Budget(0.000001)
try:
    vymodels.chat("Reply with the single word OK.")        # first call is allowed and uses the budget up
    try:
        vymodels.chat("Reply with the single word OK.")
        raise AssertionError("second call must be refused: the budget is spent")
    except vymodels.BudgetExceeded as e:
        print("budget limit: refused ->", e)
finally:
    vymodels.BUDGET = old
print("failure lab passed: retries are bounded, validation fails fast, spend is capped")
