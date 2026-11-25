import time

import gcp
import rag

corpus = rag.corpus_name()
before = len(rag.files(corpus))
gcp.storage_client().bucket("facilities-docs").blob("docs/safety-bulletin-2026-11.md").upload_from_string(
    b"# Bulletin 2026-11\nChilled water loop flush is scheduled for Saturday. Notify tenants on floors 3 to 5.")
for _ in range(40):
    after = len(rag.files(corpus))
    if after > before:
        break
    time.sleep(0.5)
print(f"indexed files: {before} -> {after}")
assert after > before
