# LoRA-train SmolLM2-135M-Instruct on CPU with PEFT as a reference for the browser engines.
import json, time, resource, sys, torch, os
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model
HF = sys.argv[1]; OUT = sys.argv[2]; EPOCHS = int(sys.argv[3]) if len(sys.argv) > 3 else 3
torch.manual_seed(0); torch.set_num_threads(int(os.environ.get("THREADS", "4")))
tok = AutoTokenizer.from_pretrained(HF); m = AutoModelForCausalLM.from_pretrained(HF, torch_dtype=torch.float32)
m = get_peft_model(m, LoraConfig(r=8, lora_alpha=16, target_modules=["q_proj","k_proj","v_proj","o_proj"], task_type="CAUSAL_LM"))
m.print_trainable_parameters()
rows = json.load(open("train.json"))
def enc(r):
    p = tok.apply_chat_template([{"role":"user","content":r["prompt"]}], tokenize=False, add_generation_prompt=True)
    pi = tok(p)["input_ids"]; ci = tok(r["completion"] + "<|im_end|>")["input_ids"]
    return pi + ci, [-100]*len(pi) + ci
data = [enc(r) for r in rows]; BS = 4
opt = torch.optim.AdamW([p for p in m.parameters() if p.requires_grad], lr=2e-4)
steps = []; t0 = time.time(); k = 0
for ep in range(EPOCHS):
    for i in range(0, len(data), BS):
        b = data[i:i+BS]; L = max(len(x) for x,_ in b)
        ids = torch.tensor([x+[tok.pad_token_id or 0]*(L-len(x)) for x,_ in b])
        lab = torch.tensor([y+[-100]*(L-len(y)) for _,y in b]); att = torch.tensor([[1]*len(x)+[0]*(L-len(x)) for x,_ in b])
        s = time.time(); loss = m(input_ids=ids, attention_mask=att, labels=lab).loss; loss.backward(); opt.step(); opt.zero_grad()
        steps.append((time.time()-s, loss.item())); k += 1
    print(f"epoch {ep} mean loss {sum(l for _,l in steps[-len(data)//BS:])/(len(data)//BS):.4f}", flush=True)
rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e6  # bytes on macOS -> MB
m.save_pretrained(OUT)
print(json.dumps({"steps": k, "first_loss": steps[0][1], "last_loss": steps[-1][1], "mean_step_s": sum(s for s,_ in steps)/k,
  "total_s": time.time()-t0, "peak_rss_mb": round(rss), "threads": torch.get_num_threads(),
  "adapter_bytes": os.path.getsize(OUT+"/adapter_model.safetensors")}))
