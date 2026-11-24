import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


class FacilitiesSupervisor:
    def set_up(self):
        import agents
        self.agents = agents

    def query(self, *, prompt: str, user: str = "anonymous") -> dict:
        st = self.agents.ask(prompt, user)
        out = {k: st.get(k) for k in ("answer", "route", "citations", "llm_used", "tools", "spans")}
        out["pid"] = os.getpid()
        return out


agent = FacilitiesSupervisor()
