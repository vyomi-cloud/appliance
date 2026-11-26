import seed
from data import DOCS
import rag
print("queue:", seed.seed())
ch = rag.build_index(DOCS)
print("passages:", len(ch))
