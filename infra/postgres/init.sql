CREATE EXTENSION IF NOT EXISTS vector;
CREATE TABLE IF NOT EXISTS documents(id UUID PRIMARY KEY,title TEXT NOT NULL,filename TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'processed',created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS document_chunks(id BIGSERIAL PRIMARY KEY,document_id UUID REFERENCES documents(id) ON DELETE CASCADE,chunk_index INT NOT NULL,content TEXT NOT NULL,metadata JSONB DEFAULT '{}'::jsonb);
CREATE TABLE IF NOT EXISTS agents(id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT DEFAULT '',role TEXT NOT NULL,enabled BOOLEAN DEFAULT TRUE);
INSERT INTO agents(id,name,description,role) VALUES
('supervisor','Supervisor Agent','Routes and coordinates specialist agents','supervisor'),
('knowledge','Knowledge Agent','Retrieves relevant knowledge','retriever'),
('analyst','Analysis Agent','Analyzes and structures information','analyst'),
('security','Security Agent','Checks prompt and response risks','guard'),
('response','Response Agent','Creates the final response','writer') ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS usage_logs(id BIGSERIAL PRIMARY KEY,request_id TEXT,provider TEXT,model TEXT,input_tokens INT DEFAULT 0,output_tokens INT DEFAULT 0,cost_usd NUMERIC(12,6) DEFAULT 0,latency_ms INT DEFAULT 0,status TEXT DEFAULT 'success',created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS traces(id BIGSERIAL PRIMARY KEY,request_id TEXT,step TEXT,status TEXT,detail JSONB DEFAULT '{}'::jsonb,created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS security_events(id BIGSERIAL PRIMARY KEY,request_id TEXT,severity TEXT,event_type TEXT,description TEXT,created_at TIMESTAMPTZ DEFAULT NOW());
ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding vector(768);
CREATE INDEX IF NOT EXISTS document_chunks_embedding_idx ON document_chunks USING hnsw (embedding vector_cosine_ops);
