import os,time,uuid,re
from contextlib import asynccontextmanager
from fastapi import FastAPI,HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,Field
from psycopg.types.json import Jsonb
from .db import init_pool,query
from .rag import add_document,documents
from .graph import graph
@asynccontextmanager
async def lifespan(app): init_pool(); yield
app=FastAPI(title="AI Intelligence Platform - AI Service",version="1.0.0",lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=["*"],allow_methods=["*"],allow_headers=["*"])
class Chat(BaseModel):
    message:str=Field(min_length=1,max_length=12000);use_rag:bool=True;model:str|None=None
class Doc(BaseModel):
    title:str=Field(min_length=1,max_length=250);content:str=Field(min_length=1,max_length=200000)
class Eval(BaseModel): question:str;answer:str;expected:str=""
@app.get("/health")
def health(): return {"status":"healthy","service":"ai-service"}
@app.post("/chat")
async def chat(b:Chat):
    start=time.perf_counter();rid=str(uuid.uuid4())
    try:
        s=await graph.ainvoke({"message":b.message,"use_rag":b.use_rag,"model":b.model,"context":[],"answer":"","trace":[],"input_tokens":0,"output_tokens":0,"selected_model":""})
        latency=int((time.perf_counter()-start)*1000);cost=s["input_tokens"]*.00000015+s["output_tokens"]*.0000006
        query("INSERT INTO usage_logs(request_id,provider,model,input_tokens,output_tokens,cost_usd,latency_ms) VALUES(%s,%s,%s,%s,%s,%s,%s)",(rid,os.getenv("LLM_PROVIDER","mock"),s["selected_model"],s["input_tokens"],s["output_tokens"],cost,latency),False)
        for t in s["trace"]: query("INSERT INTO traces(request_id,step,status,detail) VALUES(%s,%s,%s,%s)",(rid,t["step"],t["status"],Jsonb(t["detail"])),False)
        return {"request_id":rid,"answer":s["answer"],"model":s["selected_model"],"input_tokens":s["input_tokens"],"output_tokens":s["output_tokens"],"cost_usd":round(cost,6),"latency_ms":latency,"sources":s["context"],"trace":s["trace"]}
    except Exception: raise HTTPException(500,"AI request failed. Check ai-service logs for details.")
@app.post("/documents")
def create_doc(b:Doc): return add_document(b.title,b.content)
@app.get("/documents")
def get_docs(): return documents()
@app.get("/agents")
def agents(): return query("SELECT id,name,description,role,enabled FROM agents ORDER BY id")
@app.get("/metrics")
def metrics():
    total=query("SELECT COUNT(*)::int requests,COALESCE(SUM(cost_usd),0)::float cost_usd,COALESCE(AVG(latency_ms),0)::int avg_latency_ms,COALESCE(SUM(input_tokens+output_tokens),0)::int total_tokens FROM usage_logs")[0]
    return {"totals":total,"recent":query("SELECT request_id,model,input_tokens,output_tokens,cost_usd::float,latency_ms,status,created_at FROM usage_logs ORDER BY id DESC LIMIT 20")}
@app.get("/traces")
def traces(): return query("SELECT id,request_id,step,status,detail,created_at FROM traces ORDER BY id DESC LIMIT 100")
@app.post("/evaluate")
def evaluate(b:Eval):
    expected=set(re.findall(r"\w+",b.expected.lower()));answer=set(re.findall(r"\w+",b.answer.lower()));score=len(expected&answer)/max(1,len(expected))
    return {"faithfulness_proxy":round(score,3),"matched_terms":len(expected&answer),"reference_terms":len(expected),"note":"Heuristic demo metric, not validated factual accuracy."}
@app.post("/security/scan")
def scan(b:dict):
    text=str(b.get("text","")).lower();patterns=["ignore previous instructions","reveal system prompt","print api key","bypass security"];hits=[p for p in patterns if p in text]
    if hits: query("INSERT INTO security_events(request_id,severity,event_type,description) VALUES(%s,%s,%s,%s)",(str(uuid.uuid4()),"high","prompt_injection",", ".join(hits)),False)
    return {"safe":not bool(hits),"severity":"high" if hits else "low","matches":hits}
@app.get("/security/events")
def events(): return query("SELECT id,request_id,severity,event_type,description,created_at FROM security_events ORDER BY id DESC LIMIT 100")
