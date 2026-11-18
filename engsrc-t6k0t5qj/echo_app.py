import os, json
class EchoAgent:
    def set_up(self):
        self.greeting = os.environ.get("GREETING", "hello")
        self.calls = 0
    def query(self, *, prompt: str, user: str = "anonymous") -> dict:
        self.calls += 1
        out = {"answer": f"{self.greeting} {user}: {prompt.upper()}", "pid": os.getpid(), "calls": self.calls}
        # the hosted process can reach the simulator with the real SDKs (same env contract as Cloud Run functions)
        try:
            from google.cloud import storage
            from google.api_core.client_options import ClientOptions
            from google.auth.credentials import AnonymousCredentials
            c = storage.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"], credentials=AnonymousCredentials(), client_options=ClientOptions(api_endpoint=os.environ["VYOMI_ENDPOINT"]))
            out["buckets_visible"] = [b.name for b in c.list_buckets()]
        except Exception as e:
            out["sdk_error"] = repr(e)[:200]
        return out
    def stream_query(self, *, prompt: str):
        for w in prompt.split():
            yield {"token": w}
agent = EchoAgent()
