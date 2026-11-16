import json, sys, torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
HF, AD = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else None)
tok = AutoTokenizer.from_pretrained(HF); m = AutoModelForCausalLM.from_pretrained(HF)
if AD: m = PeftModel.from_pretrained(m, AD)
rows = json.load(open("heldout.json")); ok = 0
for r in rows:
    ids = tok.apply_chat_template([{"role":"user","content":r["prompt"]}], add_generation_prompt=True, return_tensors="pt", return_dict=True)
    o = m.generate(**ids, max_new_tokens=16, do_sample=False)
    out = tok.decode(o[0][ids["input_ids"].shape[1]:], skip_special_tokens=True).strip()
    ok += out == r["completion"]
print("exact-match", ok, "/", len(rows), "example:", repr(out))
