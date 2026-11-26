# Chapter 3: Tools

_Three tools that behave the same whoever calls them, and a first agent that uses them_

**What you build:** Give the agent its three tools: search the handbook in S3, look up a record in DynamoDB, and file a ticket to an SQS queue.

## Code, in order

### 1. Describe the data

The six handbook documents (one carries a planted instruction, for chapter 6), the asset and work-order records and the resource names.

- File: [`data.py`](./data.py)

### 2. Create the resources

A bucket for the handbook, a table for records and tickets, a table for memory and a queue for tickets. Safe to run again.

- File: [`seed.py`](./seed.py)
- Run: `python seed.py`
- You should see: `documents: 7`

### 3. Write the three tools

search_docs (keyword search over the S3 documents), lookup_record and file_ticket. The ticket id comes from the request, so asking twice files once.

- File: [`tools.py`](./tools.py)

### 4. Test the tools by hand

No model yet: call each tool directly and check what it returns, including what it must refuse.

- File: [`try_tools.py`](./try_tools.py)
- Run: `python try_tools.py`
- You should see: `tools ok`

### 5. Connect the model to the tools

The loop from chapter 1 with the model as its brain. The menu follows the state: no evidence yet means no answer; evidence in hand means no giving up.

- File: [`agent.py`](./agent.py)

### 6. Run the first agent

Two questions, one tool each. This step needs a model.

- File: [`try_agent.py`](./try_agent.py)
- Run: `python try_agent.py`
- You should see: `first agent ok`

## It works when

- the bucket, two tables and the queue exist
- search finds the boiler procedure and returns nothing for an unsupported question
- a record is found and a missing one is reported
- a ticket reaches the queue once even when requested twice
- the first agent picks the right tool for two questions
