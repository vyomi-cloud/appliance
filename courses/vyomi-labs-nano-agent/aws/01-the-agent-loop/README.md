# Chapter 1: The agent loop

_A working loop with a step limit and a way to say no, ready for a model to drive it_

**What you build:** Understand what an agent is by building the smallest one: a loop that picks an action, runs it and looks at the result.

## Code, in order

### 1. Write the loop

Fifty lines: a notebook of facts, one tool, a rule-based brain and the loop that connects them. Read run() first.

- File: [`loop.py`](./loop.py)
- Run: `python loop.py`
- You should see: `finished: answer after 2 steps`

### 2. Test the limits

A brain that never answers must be stopped, and a question with nothing to look up must be refused.

- File: [`loop_limits.py`](./loop_limits.py)
- Run: `python loop_limits.py`
- You should see: `loop limits ok`

## It works when

- the loop answers a question in two steps
- a brain that never decides is stopped by the step limit
- a question it cannot support is refused
