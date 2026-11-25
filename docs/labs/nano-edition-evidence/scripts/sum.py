import json,sys,collections
def load(f):
    d=collections.OrderedDict()
    for l in open(f):
        r=json.loads(l)
        if r.get('run'): d[(r['chapter'],r['file'])]=r['status']=='PASS'
    return d
def per(d):
    c=collections.OrderedDict()
    for (ch,f),ok in d.items():
        a=c.setdefault(ch,[0,0]); a[1]+=1; a[0]+=ok
    return c
fs=sys.argv[1:]
data=[per(load(f)) for f in fs]
print("| Ch | "+" | ".join(f.split('/')[-1].replace('.jsonl','') for f in fs)+" |")
chs=sorted({c for d in data for c in d})
for c in chs: print(f"| {c} | "+" | ".join(f"{d[c][0]}/{d[c][1]}" if c in d else "-" for d in data)+" |")
print("| all | "+" | ".join(f"{sum(a[0] for a in d.values())}/{sum(a[1] for a in d.values())}" for d in data)+" |")
