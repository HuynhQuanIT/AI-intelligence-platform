import { useEffect, useState } from 'react';
import { Download, FileText, Lock, Plus, Save, Trash2, Upload } from 'lucide-react';
import { api, apiFetch, downloadDocument } from '../api/client';
import Panel from '../components/Panel';
import '../components/extras.css';
import type { DocumentDetail, DocumentRow, Group, PlatformData } from '../types';

// canEdit: chỉ admin được thêm, tải lên và xóa tài liệu; user thường chỉ xem (server cũng kiểm tra).
type Props = Pick<PlatformData, 'docs' | 'refresh' | 'setErr'> & { canEdit: boolean };

export default function KnowledgeCenter({ docs, refresh, setErr, canEdit }: Props) {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [selectedDoc, setSelectedDoc] = useState<DocumentDetail | null>(null);
  const [loadingDoc, setLoadingDoc] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadNote, setUploadNote] = useState('');
  // Phân quyền theo nhóm (admin): danh sách nhóm, tài liệu đang sửa quyền và các nhóm đã tick.
  const [allGroups, setAllGroups] = useState<Group[]>([]);
  const [accessDocId, setAccessDocId] = useState('');
  const [accessIds, setAccessIds] = useState<Set<string>>(new Set());
  const [savingAccess, setSavingAccess] = useState(false);

  useEffect(() => {
    if (!canEdit) return;
    api('/groups').then(setAllGroups).catch(() => setAllGroups([]));
  }, [canEdit, docs.length]);

  function editAccess(doc: DocumentRow) {
    if (accessDocId === doc.id) {
      setAccessDocId('');
      return;
    }
    setAccessDocId(doc.id);
    setAccessIds(new Set((doc.groups ?? []).map((g) => g.id)));
  }

  async function saveAccess() {
    try {
      setSavingAccess(true);
      setErr('');
      await api(`/documents/${encodeURIComponent(accessDocId)}/groups`, {
        method: 'PUT',
        body: JSON.stringify({ ids: [...accessIds] }),
      });
      setAccessDocId('');
      await refresh();
    } catch (error: any) {
      setErr('Không lưu được quyền xem: ' + error.message);
    } finally {
      setSavingAccess(false);
    }
  }

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

      const response = await apiFetch('/documents/upload', {
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

  async function download(doc: DocumentRow) {
    try {
      setErr('');
      await downloadDocument(doc.id, doc.filename);
    } catch (error: any) {
      setErr('Không tải được file: ' + error.message);
    }
  }

  return (
    <>
      {canEdit ? (
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
      ) : (
        <p className="note">Bạn chỉ có quyền xem tài liệu. Quản trị viên mới được thêm, tải lên hoặc xóa.</p>
      )}

      {/* Indexed document list */}
      <Panel title={`Indexed documents (${docs.length})`}>
        {docs.length ? (
          docs.map((doc) => (
            <div key={doc.id}>
              <div className="row">
                <FileText />

                <div>
                  <b>{doc.title}</b>
                  <small>
                    {doc.filename} · {doc.size_bytes ? `${(doc.size_bytes / 1024).toFixed(1)} KB · ` : ''}
                    {new Date(doc.created_at).toLocaleString()}
                  </small>
                  {canEdit && (
                    <div>
                      {doc.groups?.length ? (
                        doc.groups.map((g) => <span className="chip" key={g.id}>{g.name}</span>)
                      ) : (
                        <span className="chip public">Công khai (mọi người đã đăng nhập)</span>
                      )}
                    </div>
                  )}
                </div>

                <em>{doc.status}</em>

                <button className="secondary" onClick={() => viewDoc(doc.id)} disabled={loadingDoc}>
                  <FileText size={15} />
                  Xem
                </button>

                {doc.has_file && (
                  <button className="secondary" onClick={() => download(doc)}>
                    <Download size={15} />
                    Tải
                  </button>
                )}

                {canEdit && (
                  <button className="secondary" onClick={() => editAccess(doc)}>
                    <Lock size={15} />
                    Quyền xem
                  </button>
                )}

                {canEdit && (
                  <button className="secondary" onClick={() => deleteDoc(doc)}>
                    <Trash2 size={15} />
                    Xóa
                  </button>
                )}
              </div>

              {canEdit && accessDocId === doc.id && (
                <div className="doc-groups">
                  <small>
                    Không chọn nhóm nào = công khai. Chọn nhóm = chỉ thành viên các nhóm đó (và admin) thấy tài liệu,
                    kể cả khi chat và khi agent dùng công cụ.
                  </small>
                  {allGroups.length ? (
                    <div className="checklist">
                      {allGroups.map((g) => (
                        <label key={g.id}>
                          <input
                            type="checkbox"
                            checked={accessIds.has(g.id)}
                            onChange={() =>
                              setAccessIds((current) => {
                                const copy = new Set(current);
                                if (copy.has(g.id)) copy.delete(g.id);
                                else copy.add(g.id);
                                return copy;
                              })
                            }
                          />
                          <span className="grow">{g.name}</span> <small>{g.member_count} người</small>
                        </label>
                      ))}
                    </div>
                  ) : (
                    <p className="muted">Chưa có nhóm nào. Tạo nhóm ở trang Groups.</p>
                  )}
                  <div className="inline-form">
                    <button className="primary" onClick={saveAccess} disabled={savingAccess}>
                      <Save size={15} />
                      Lưu quyền xem
                    </button>
                    <button className="secondary" onClick={() => setAccessDocId('')}>Hủy</button>
                  </div>
                </div>
              )}
            </div>
          ))
        ) : (
          <p className="muted">{canEdit ? 'No documents yet. Add one above.' : 'Chưa có tài liệu nào.'}</p>
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
