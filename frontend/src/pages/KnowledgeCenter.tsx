import { useState } from 'react';
import { Download, FileText, Plus, Trash2, Upload } from 'lucide-react';
import { API, api } from '../api/client';
import Panel from '../components/Panel';
import type { DocumentDetail, DocumentRow, PlatformData } from '../types';

type Props = Pick<PlatformData, 'docs' | 'refresh' | 'setErr'>;

export default function KnowledgeCenter({ docs, refresh, setErr }: Props) {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [selectedDoc, setSelectedDoc] = useState<DocumentDetail | null>(null);
  const [loadingDoc, setLoadingDoc] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadNote, setUploadNote] = useState('');

  async function addDoc() {
    try {
      await api('/documents', {
        method: 'POST',
        body: JSON.stringify({ title, content }),
      });

      setTitle('');
      setContent('');

      await refresh();
    } catch (error: any) {
      setErr(error.message);
    }
  }

  async function uploadFile() {
    if (!file) return;

    try {
      setUploading(true);
      setErr('');
      setUploadNote('');

      // Không dùng api(): nó ép Content-Type JSON, còn multipart cần boundary do trình duyệt tự đặt.
      const form = new FormData();
      form.append('file', file);
      if (title.trim()) form.append('title', title.trim());

      const response = await fetch(API + '/documents/upload', {
        method: 'POST',
        body: form,
      });

      const body = await response.json().catch(() => null);

      if (!response.ok) {
        throw new Error(
          typeof body?.detail === 'string' ? body.detail : `Upload thất bại (HTTP ${response.status})`
        );
      }

      setUploadNote(
        `Đã index "${body.title}": ${body.chunks} chunks` +
          (body.embedded ? ', đã embedding.' : ', CHƯA có embedding (chạy reindex).') +
          (body.security_matches?.length
            ? ` Cảnh báo: nội dung có mẫu nghi prompt injection (${body.security_matches.join(', ')}); sẽ bị lọc khi truy xuất.`
            : '')
      );

      setFile(null);
      setFileInputKey((key) => key + 1);
      setTitle('');

      await refresh();
    } catch (error: any) {
      setErr(error.message);
    } finally {
      setUploading(false);
    }
  }

  async function deleteDoc(doc: DocumentRow) {
    if (!window.confirm(`Xóa tài liệu "${doc.title}"? Nội dung, vector và file gốc sẽ bị xóa vĩnh viễn.`)) {
      return;
    }

    try {
      setErr('');
      await api(`/documents/${encodeURIComponent(doc.id)}`, { method: 'DELETE' });

      if (selectedDoc?.id === doc.id) setSelectedDoc(null);

      await refresh();
    } catch (error: any) {
      setErr('Không xóa được tài liệu: ' + error.message);
    }
  }

  async function viewDoc(documentId: string) {
    try {
      setLoadingDoc(true);
      setSelectedDoc(null);
      setErr('');

      setSelectedDoc(await api(`/documents/${encodeURIComponent(documentId)}`));
    } catch (error: any) {
      setErr('Cannot load document: ' + error.message);
    } finally {
      setLoadingDoc(false);
    }
  }

  return (
    <>
      <div className="cols">
        <Panel title="Add knowledge">
          <label>Document title</label>

          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Product handbook" />

          <label>Document content</label>

          <textarea
            rows={8}
            value={content}
            onChange={(event) => setContent(event.target.value)}
            placeholder="Paste document text..."
          />

          <button className="primary" disabled={!title.trim() || !content.trim()} onClick={addDoc}>
            <Plus size={16} />
            Index document
          </button>

          <label>Hoặc tải file lên (.pdf, .docx, .txt, .md - tối đa 10 MB)</label>

          <input
            key={fileInputKey}
            type="file"
            accept=".pdf,.docx,.txt,.md"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />

          <button className="primary" disabled={!file || uploading} onClick={uploadFile}>
            <Upload size={16} />
            {uploading ? 'Đang xử lý...' : 'Upload và index'}
          </button>

          {uploadNote && <p className="note">{uploadNote}</p>}
        </Panel>

        <Panel title="Retrieval configuration">
          <div className="kv">
            Chunk size <b>900 characters</b>
          </div>

          <div className="kv">
            Overlap <b>150 characters</b>
          </div>

          <div className="kv">
            Retriever <b>Hybrid (keyword + pgvector)</b>
          </div>

          <div className="kv">
            Top-K <b>4</b>
          </div>

          <p className="note">
            Vector search chạy khi LLM_PROVIDER=gemini; nếu không sẽ tự quay về tìm theo từ khóa. File upload được lưu
            gốc trong volume Docker, văn bản được chia chunk theo đoạn.
          </p>
        </Panel>
      </div>

      {/* Indexed document list */}
      <Panel title={`Indexed documents (${docs.length})`}>
        {docs.length ? (
          docs.map((doc) => (
            <div className="row" key={doc.id}>
              <FileText />

              <div>
                <b>{doc.title}</b>
                <small>
                  {doc.filename} · {doc.size_bytes ? `${(doc.size_bytes / 1024).toFixed(1)} KB · ` : ''}
                  {new Date(doc.created_at).toLocaleString()}
                </small>
              </div>

              <em>{doc.status}</em>

              <button className="secondary" onClick={() => viewDoc(doc.id)} disabled={loadingDoc}>
                <FileText size={15} />
                Xem
              </button>

              {doc.has_file && (
                <a
                  className="secondary"
                  href={`${API}/documents/${encodeURIComponent(doc.id)}/file`}
                  download
                  style={{ textDecoration: 'none' }}
                >
                  <Download size={15} />
                  Tải
                </a>
              )}

              <button className="secondary" onClick={() => deleteDoc(doc)}>
                <Trash2 size={15} />
                Xóa
              </button>
            </div>
          ))
        ) : (
          <p className="muted">No documents yet. Add one above.</p>
        )}
      </Panel>

      {/* Document detail */}
      {loadingDoc && (
        <Panel title="Document details">
          <p className="muted">Đang tải nội dung tài liệu...</p>
        </Panel>
      )}

      {selectedDoc && !loadingDoc && (
        <Panel title={`Document: ${selectedDoc.title}`}>
          <div className="row">
            <div>
              <b>{selectedDoc.filename}</b>
              <small>
                Trạng thái: {selectedDoc.status}
                {' · '}
                Số chunks: {selectedDoc.chunks?.length ?? 0}
              </small>
            </div>

            <button className="secondary" onClick={() => setSelectedDoc(null)}>
              Đóng
            </button>
          </div>

          <div className="document-content">
            {selectedDoc.chunks?.length ? (
              selectedDoc.chunks.map((chunk) => (
                <section key={chunk.chunk_index} className="document-chunk">
                  <h4>Chunk {chunk.chunk_index}</h4>

                  <pre
                    style={{
                      whiteSpace: 'pre-wrap',
                      overflowWrap: 'anywhere',
                      fontFamily: 'inherit',
                      lineHeight: 1.6,
                    }}
                  >
                    {chunk.content}
                  </pre>
                </section>
              ))
            ) : (
              <p className="muted">Tài liệu chưa có nội dung chunks để hiển thị.</p>
            )}
          </div>
        </Panel>
      )}
    </>
  );
}
