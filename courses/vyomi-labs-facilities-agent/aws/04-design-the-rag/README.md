# Layer 4: Design the RAG

_A tested RAG design saved as rag-design.json, read by the pipeline, search and response chapters_

**What you build:** Design the retrieval-augmented generation the later chapters build: chunking, embedding, search, rerank and grounding, tested on a golden set and saved as one design file.

## Code, in order

### 1. Write the design loader

Every later chapter that chunks, searches or answers imports this one file instead of hard-coding its settings. It finds your design file, merges it over the defaults (which are exactly the values the course used before this chapter existed), and returns plain numbers. A value that is out of range prints a warning and falls back to its default, so a typo never stops a chapter.

- File: [`rag_design.py`](./rag_design.py)

### 2. Save the starting design

The design file, in the schema `vyomi.rag-design/v1` writes when you export a design. This one is the course's starting point, so saving it changes nothing yet. Replace it with the file you export from Bedrock, RAG Studio once you have tuned and tested your own design: chapters 12, 6 and 11 will build and answer with your numbers. Keep the name `rag-design.json` next to your other files.

- File: [`rag-design.json`](./rag-design.json)

### 3. Check the design

Loads the design the way the later chapters will, checks every value against its allowed range and prints what they will use. Run it after every change to `rag-design.json`.

- File: [`show_design.py`](./show_design.py)
- Run: `python show_design.py` (or `./run_all.sh 4` from the project root)
- You should see: `design OK`

## It works when

- rag-design.json is saved next to your code
- show_design.py prints design OK
- the loader returns the same values as the file
