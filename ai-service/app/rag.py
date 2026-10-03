import re,uuid
from .db import query
def words(s): return set(re.findall(r"\w+",s.lower()))
def add_document(title,content):
    did=str(uuid.uuid4()); chunks=[content[i:i+900] for i in range(0,len(content),750)] or [content]
    query("INSERT INTO documents(id,title,filename) VALUES(%s,%s,%s)",(did,title,title),False)
    for i,c in enumerate(chunks): query("INSERT INTO document_chunks(document_id,chunk_index,content) VALUES(%s,%s,%s)",(did,i,c),False)
    return {"id":did,"title":title,"chunks":len(chunks),"status":"processed"}
def retrieve(question,limit=4):
    rows=query("SELECT d.title,c.content,c.document_id,c.chunk_index FROM document_chunks c JOIN documents d ON d.id=c.document_id ORDER BY c.id DESC LIMIT 500")
    q=words(question); ranked=[]
    for r in rows:
        score=len(q & words(r["content"]))/max(1,len(q))
        if score: ranked.append((score,r))
    ranked.sort(key=lambda x:x[0],reverse=True)
    return [{"title":r["title"],"content":r["content"],"score":round(s,3),"document_id":str(r["document_id"]),"chunk_index":r["chunk_index"]} for s,r in ranked[:limit]]
def documents(): return query("SELECT id::text,title,filename,status,created_at FROM documents ORDER BY created_at DESC")
