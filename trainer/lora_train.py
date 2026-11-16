#!/usr/bin/env python3
"""Vyomi chat-model LoRA trainer (standalone, CPU, on demand; NOT part of the Mesh image).

    python lora_train.py --base <hf repo|dir> --data train.jsonl --out outdir [--epochs 3 --rank 8 --alpha 16 --lr 2e-4
                         --max-seq 256 --batch 4 --max-rows 2000 --events events.jsonl --cancel-file cancel --llamacpp <dir>]

Rows: {"messages":[{"role","content"},...]} or {"prompt","completion"} (JSONL). Loss is on the LAST assistant turn only.
Progress is appended to --events as JSON lines (and echoed to stdout):
  {"event":"status","status":"Embedding|Training|Evaluating|Converting"}  {"event":"step","step","steps","epoch","loss"}
  {"event":"epoch","epoch","loss","accuracy","valLoss"}  {"event":"done","heldOut":{...},"adapter":"adapter.gguf",...}  {"event":"error","error"}
Cancel: create the --cancel-file (checked every step) -> exit code 3.
Outputs: outdir/peft/ (PEFT adapter), outdir/adapter.gguf (f16 GGUF LoRA via llama.cpp convert_lora_to_gguf.py), outdir/result.json.
"""
import argparse, json, math, os, random, resource, subprocess, sys, time


def emit(path, **ev):
    line = json.dumps(ev)
    print(line, flush=True)
    if path:
        with open(path, "a") as f:
            f.write(line + "\n")


def load_rows(path, max_rows, max_bytes):
    raw = open(path, "rb").read()
    if len(raw) > max_bytes:
        raise SystemExit(f"training data is {len(raw)} bytes; limit {max_bytes}")
    rows = []
    for i, ln in enumerate(raw.decode("utf-8", "replace").splitlines(), 1):
        if not ln.strip():
            continue
        r = json.loads(ln)
        if isinstance(r.get("messages"), list) and r["messages"]:
            m = [{"role": x["role"], "content": x["content"]} for x in r["messages"]]
        elif isinstance(r.get("prompt"), str) and isinstance(r.get("completion"), str):
            m = [{"role": "user", "content": r["prompt"]}, {"role": "assistant", "content": r["completion"]}]
        else:
            raise SystemExit(f"row {i}: need messages or prompt/completion")
        if m[-1]["role"] != "assistant":
            raise SystemExit(f"row {i}: last message must be the assistant turn to learn")
        rows.append(m)
        if len(rows) > max_rows:
            raise SystemExit(f"more than {max_rows} rows")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True); ap.add_argument("--data", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=3); ap.add_argument("--rank", type=int, default=8); ap.add_argument("--alpha", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-4); ap.add_argument("--max-seq", type=int, default=256); ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--max-rows", type=int, default=2000); ap.add_argument("--max-bytes", type=int, default=5 * 1024 * 1024)
    ap.add_argument("--heldout-frac", type=float, default=0.1); ap.add_argument("--eval-n", type=int, default=30)
    ap.add_argument("--dtype", default="float32", choices=["float32", "bfloat16"]); ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--events"); ap.add_argument("--cancel-file"); ap.add_argument("--llamacpp"); ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--no-gguf", action="store_true")
    a = ap.parse_args()
    ev = lambda **k: emit(a.events, **k)
    cancelled = lambda: bool(a.cancel_file and os.path.exists(a.cancel_file))
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        from peft import LoraConfig, get_peft_model
        torch.manual_seed(a.seed); random.seed(a.seed)
        if a.threads:
            torch.set_num_threads(a.threads)
        os.makedirs(a.out, exist_ok=True)
        ev(event="status", status="Embedding", note="loading base model")
        rows = load_rows(a.data, a.max_rows, a.max_bytes)
        from huggingface_hub import snapshot_download
        base_dir = a.base if os.path.isdir(a.base) else snapshot_download(a.base, allow_patterns=["*.json", "*.safetensors", "*.model", "*.txt", "*.jinja", "tokenizer*"])
        tok = AutoTokenizer.from_pretrained(base_dir)
        model = AutoModelForCausalLM.from_pretrained(base_dir, dtype=getattr(torch, a.dtype))
        pad = tok.pad_token_id if tok.pad_token_id is not None else (tok.eos_token_id or 0)

        def enc(m):
            p = tok.apply_chat_template(m[:-1], tokenize=False, add_generation_prompt=True)
            full = tok.apply_chat_template(m, tokenize=False)
            pi = tok(p, add_special_tokens=False)["input_ids"]
            fi = tok(full, add_special_tokens=False)["input_ids"]
            if fi[:len(pi)] != pi:                                    # template without a clean prefix: fall back to concatenation
                fi = pi + tok(m[-1]["content"] + (tok.eos_token or ""), add_special_tokens=False)["input_ids"]
            fi = fi[:a.max_seq]
            if len(pi) >= len(fi):                                    # prompt alone fills the window: nothing to learn
                return None
            return fi, [-100] * len(pi) + fi[len(pi):], m
        data = [e for e in (enc(m) for m in rows) if e]
        dropped = len(rows) - len(data)
        random.Random(a.seed).shuffle(data)
        nho = max(2, int(len(data) * a.heldout_frac))
        ho, tr = data[:nho], data[nho:]
        if len(tr) < 2:
            raise SystemExit("not enough trainable rows after truncation")
        model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=a.alpha, lora_dropout=0.0, task_type="CAUSAL_LM",
                                                 target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]))
        ntrain = sum(p.numel() for p in model.parameters() if p.requires_grad)

        def batch(items):
            L = max(len(x[0]) for x in items)
            ids = torch.tensor([x[0] + [pad] * (L - len(x[0])) for x in items])
            lab = torch.tensor([x[1] + [-100] * (L - len(x[1])) for x in items])
            att = torch.tensor([[1] * len(x[0]) + [0] * (L - len(x[0])) for x in items])
            return ids, lab, att

        @torch.no_grad()
        def nll(items):
            model.eval(); tot = n = 0
            for i in range(0, len(items), a.batch):
                ids, lab, att = batch(items[i:i + a.batch])
                lg = model(input_ids=ids, attention_mask=att).logits[:, :-1].float()
                tg = lab[:, 1:]
                l = torch.nn.functional.cross_entropy(lg.reshape(-1, lg.size(-1)), tg.reshape(-1), ignore_index=-100, reduction="sum")
                tot += l.item(); n += (tg != -100).sum().item()
            return tot / max(1, n)

        @torch.no_grad()
        def exact(items, new_tokens=64):
            model.eval(); ok = 0
            for ids, lab, m in [(x[0], x[1], x[2]) for x in items[:a.eval_n]]:
                k = next(i for i, v in enumerate(lab) if v != -100)
                gen = model.generate(torch.tensor([ids[:k]]), max_new_tokens=min(new_tokens, len(ids) - k + 8), do_sample=False, pad_token_id=pad)
                out = tok.decode(gen[0][k:], skip_special_tokens=True).strip()
                ok += 1 if out == m[-1]["content"].strip() else 0
            return ok / max(1, min(len(items), a.eval_n))

        ev(event="status", status="Evaluating", note="baseline (adapter disabled)")
        with model.disable_adapter():
            base_ppl_nll, base_em = nll(ho), exact(ho)
        spe = math.ceil(len(tr) / a.batch)
        steps, step, t0, step_times = a.epochs * spe, 0, time.time(), []
        opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr)
        ev(event="status", status="Training", rows=len(data), heldoutRows=len(ho), steps=steps, trainable=ntrain, dropped=dropped)
        for ep in range(1, a.epochs + 1):
            random.shuffle(tr); model.train(); el = er = 0.0; en = 0
            for i in range(0, len(tr), a.batch):
                if cancelled():
                    ev(event="cancelled", step=step); sys.exit(3)
                s = time.time()
                ids, lab, att = batch(tr[i:i + a.batch])
                out = model(input_ids=ids, attention_mask=att, labels=lab)
                out.loss.backward(); opt.step(); opt.zero_grad()
                step += 1; step_times.append(time.time() - s)
                with torch.no_grad():
                    pr = out.logits[:, :-1].argmax(-1); tg = lab[:, 1:]; msk = tg != -100
                    acc = ((pr == tg) & msk).sum().item() / max(1, msk.sum().item())
                el += out.loss.item(); er += acc; en += 1
                ev(event="step", step=step, steps=steps, epoch=ep, loss=round(out.loss.item(), 5))
            vl = nll(ho)
            ev(event="epoch", epoch=ep, loss=round(el / en, 5), accuracy=round(er / en, 4), valLoss=round(vl, 5))
        ev(event="status", status="Evaluating", note="held-out, adapter on")
        tuned_nll, tuned_em = nll(ho), exact(ho)
        model.save_pretrained(os.path.join(a.out, "peft"))
        gguf = None
        if not a.no_gguf:
            ev(event="status", status="Evaluating", note="converting adapter to GGUF")
            conv = os.path.join(a.llamacpp or os.environ.get("LLAMACPP_DIR", "/opt/llama.cpp"), "convert_lora_to_gguf.py")
            gguf = os.path.join(a.out, "adapter.gguf")
            r = subprocess.run([sys.executable, conv, "--base", base_dir, "--outtype", "f16", "--outfile", gguf, os.path.join(a.out, "peft")], capture_output=True, text=True)
            if r.returncode != 0 or not os.path.exists(gguf):
                raise RuntimeError("GGUF conversion failed: " + (r.stderr or r.stdout)[-600:])
        res = {"heldOut": {"exactMatch": round(tuned_em, 4), "baselineExactMatch": round(base_em, 4), "perplexity": round(math.exp(tuned_nll), 4),
                           "baselinePerplexity": round(math.exp(base_ppl_nll), 4), "n": len(ho), "exactMatchN": min(len(ho), a.eval_n),
                           "accuracy": round(tuned_em, 4), "baseline": round(base_em, 4), "baselineKind": "base model, adapter disabled, greedy exact match"},
               "rows": len(data), "dropped": dropped, "rank": a.rank, "alpha": a.alpha, "steps": step, "trainableParams": ntrain, "base": a.base,
               "meanStepS": round(sum(step_times) / len(step_times), 3), "totalS": round(time.time() - t0, 1),
               "peakRssMB": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1e6 if sys.platform == "darwin" else 1e3)),
               "adapterBytes": os.path.getsize(gguf) if gguf else None, "adapter": "adapter.gguf" if gguf else None, "torch": torch.__version__}
        json.dump(res, open(os.path.join(a.out, "result.json"), "w"))
        ev(event="done", **res)
    except SystemExit as e:
        if e.code in (3, 0, None):
            raise
        ev(event="error", error=str(e.code)); sys.exit(2)
    except Exception as e:  # noqa: BLE001
        ev(event="error", error=f"{type(e).__name__}: {e}"); sys.exit(1)


if __name__ == "__main__":
    main()
