import json, re
from pathlib import Path

def load_knowledge(path):
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data,list): raise ValueError("知识库必须是 JSON 数组")
    required={"knowledge_id","property_id","question","answer","status","source"}
    for i,item in enumerate(data):
        if required-set(item): raise ValueError(f"第{i+1}条知识缺少字段")
    return data

def _terms(text):
    s=text.lower().strip()
    terms=set(re.findall(r"[a-z0-9]+",s))
    compact=re.sub(r"\\s+","",s)
    terms.update(compact[i:i+2] for i in range(max(0,len(compact)-1)))
    terms.update(compact)
    return {x for x in terms if len(x)>1}

def search_knowledge(query,property_id,knowledge_base,top_k=3):
    if not query.strip() or top_k<1:return []
    q=_terms(query); out=[]
    for item in knowledge_base:
        if item.get("property_id")!=property_id or item.get("status")!="active":continue
        corpus=" ".join([item.get("question",""),item.get("answer","")," ".join(item.get("keywords",[])),item.get("category","")])
        overlap=q&_terms(corpus)
        explicit=sum(2 for kw in item.get("keywords",[]) if kw.lower() in query.lower())
        score=len(overlap)+explicit+1.5*len(q&_terms(item.get("question","")))
        if score>0:out.append({**item,"score":round(score,3)})
    return sorted(out,key=lambda x:(x["score"],x["knowledge_id"]),reverse=True)[:top_k]
