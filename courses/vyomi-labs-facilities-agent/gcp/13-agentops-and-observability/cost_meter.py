from vymodels import chat

PRICE_PER_1K = 0.0006      # notional price per 1,000 tokens: put the real rate card here


class BudgetExceeded(Exception):
    pass


class Budget:
    def __init__(self, layer, limit_usd):
        self.layer, self.limit, self.spent, self.calls = layer, limit_usd, 0.0, 0

    def charge(self, text_in, text_out):
        cost = (len(text_in) + len(text_out)) / 4 / 1000 * PRICE_PER_1K
        if self.spent + cost > self.limit:
            raise BudgetExceeded(f"{self.layer}: {self.spent + cost:.6f} would exceed the {self.limit:.6f} limit")
        self.spent += cost
        self.calls += 1


budget = Budget("agents", limit_usd=0.0004)
refused = None
for _ in range(200):
    q = "Summarise the boiler shutdown procedure in one sentence. " * 3
    try:
        budget.charge(q, chat(q))
    except BudgetExceeded as e:
        refused = str(e)
        break
assert refused, "the budget must trip before 200 calls"
assert budget.spent <= budget.limit
print("calls allowed:", budget.calls, "| spent:", round(budget.spent, 6), "| limit:", budget.limit)
print("refused:", refused)
print("cost limit verified")
