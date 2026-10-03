import os,httpx
async def generate(prompt,model=None):
    provider=os.getenv("LLM_PROVIDER","mock").lower(); selected=model or os.getenv("OPENAI_MODEL","gpt-4o-mini")
    if provider=="openai" and os.getenv("OPENAI_API_KEY"):
        async with httpx.AsyncClient(timeout=60) as c:
            r=await c.post("https://api.openai.com/v1/chat/completions",headers={"Authorization":"Bearer "+os.environ["OPENAI_API_KEY"]},json={"model":selected,"messages":[{"role":"user","content":prompt}],"temperature":0.2})
            r.raise_for_status(); data=r.json()
            return data["choices"][0]["message"]["content"],data.get("usage",{}).get("prompt_tokens",0),data.get("usage",{}).get("completion_tokens",0),selected
    answer="[DEMO MODE] Request received. Context and task:\n"+prompt[-1600:]+"\n\nConfigure a hosted LLM provider for real model-generated responses."
    return answer,max(1,len(prompt)//4),max(1,len(answer)//4),"mock-local"
