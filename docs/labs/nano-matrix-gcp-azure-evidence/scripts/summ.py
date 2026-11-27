import json,re,sys
d=json.load(open(sys.argv[1]))
def norm(p): return re.sub(r'\d{6,}','N',p.split('?')[0])
seen=set(); n_ok=0; n=0
for r in d:
    n+=1
    ok = (r['nano_status']//100==2)==(r['ref_status']//100==2)
    if ok: n_ok+=1; continue
    k=(r['tag'],r['method'],norm(r['path']),r['nano_status'])
    if k in seen: continue
    seen.add(k)
    print(r['tag'],r['method'],norm(r['path'])[:105],r['ref_status'],'->',r['nano_status'],'|',r['nano_head'][:120].replace("\n"," "))
print("same-class:",n_ok,"of",n)
