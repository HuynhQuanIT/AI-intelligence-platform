import { useEffect, useState } from 'react';
import { Download, FileText, Loader2, Lock, Plus, RefreshCw, Save, Trash2, Upload } from 'lucide-react';
import { api, apiFetch, downloadDocument } from '../api/client';
import Panel from '../components/Panel';
import '../components/extras.css';
import type { DocumentDetail, DocumentRow, Group, PlatformData } from '../types';

function StatusBadge({ status }: { status: string }) {
  if (status === 'processing') {
    return <span className="status-badge processing"><Loader2 size={13} className="spin" /> Đang xử lý…</span>;
  }
  if (status === 'failed') return <span className="status-badge failed">Lỗi</span>;
  return <span className="status-badge processed">Đã xử lý</span>;
}

// canEdit: chỉ admin được thêm, tải lên và xóa tài liệu; user thường chỉ xem (server cũng kiểm tra).
type Props = Pick<PlatformData, 'docs' | 'refresh' | 'refreshDocs' | 'setErr'> & {
  canEdit: boolean;
  // Mở sẵn một tài liệu và cuộn tới đúng đoạn (từ kết quả tìm kiếm / nguồn trích dẫn).
  focus?: { documentId: string; chunkIndex?: number | null } | null;
  onFocusDone?: () => void;
};

export default function KnowledgeCenter({ docs, refresh, refreshDocs, setErr, canEdit, focus, onFocusDone }: Props) {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [selectedDoc, setSelectedDoc] = useState<DocumentDetail | null>(null);
  const [loadingDoc, setLoadingDoc] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [adding, setAdding] = useState(false);
  const [uploadNote, setUploadNote] = useState('');
  // Phân quyền theo nhóm (admin): danh sách nhóm, tài liệu đang sửa quyền và các nhóm đã tick.
  const [allGroups, setAllGroups] = useState<Group[]>([]);
  const [accessDocId, setAccessDocId] = useState('');
  const [accessIds, setAccessIds] = useState<Set<string>>(new Set());
  const [savingAccess, setSavingAccess] = useState(false);
  // User thường: lọc theo "tài liệu của nhóm tôi" hoặc "công khai".
  const [scopeFilter, setScopeFilter] = useState<'all' | 'own' | 'mine' | 'public'>('all');
  const [adminFilter, setAdminFilter] = useState<'all' | 'private'>('all');
  const shownDocs = canEdit ? (adminFilter === 'private' ? docs.filter((d) => !!d.owner_id) : docs) : docs.filter((d) =>
    scopeFilter === 'all' ? true : scopeFilter === 'own' ? !!d.mine : scopeFilter === 'mine' ? d.scope === 'group' : d.scope === 'public');

  // Được mở từ nơi khác: nạp tài liệu rồi cuộn tới đoạn cần xem và tô nổi bật.
  const [focusChunk, setFocusChunk] = useState<number | null>(null);
  useEffect(() => {
    if (!focus) return;
    setFocusChunk(focus.chunkIndex ?? null);
    viewDoc(focus.documentId).finally(() => onFocusDone?.());
  }, [focus]);
  useEffect(() => {
    if (!selectedDoc) return;
    const el = focusChunk != null ? document.getElementById(`chunk-${focusChunk}`) : null;
    (el ?? document.getElementById('document-viewer'))?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [selectedDoc, focusChunk]);

  // Admin: file người dùng đính kèm trong chat xuất hiện bất cứ lúc nào, nên tự nạp lại danh sách định kỳ
  // và khi quay lại tab (không cần bấm Refresh).
  useEffect(() => {
    if (!canEdit) return;
    const timer = window.setInterval(() => { refreshDocs(); }, 15000);
    const onVisible = () => { if (document.visibilityState === 'visible') refreshDocs(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => { window.clearInterval(timer); document.removeEventListener('visibilitychange', onVisible); };
  }, [canEdit]);

  // Còn tài liệu đang xử lý nền: tự hỏi lại mỗi 3 giây cho tới khi xong (processed/failed).
  const hasProcessing = docs.some((d) => d.status === 'processing');
  useEffect(() => {
    if (!hasProcessing) return;
    const timer = window.setInterval(() => { refreshDocs(); }, 3000);
    return () => window.clearInterval(timer);
  }, [hasProcessing, refreshDocs]);

  async function retryDoc(doc: DocumentRow) {
    try {
      setErr('');
      await api(`/documents/${encodeURIComponent(doc.id)}/retry`, { method: 'POST' });
      await refreshDocs();
    } catch (error: any) {
      setErr(error.message);
    }
  }

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
    if (adding) return; // đang index: bấm thêm lần nữa sẽ tạo bản trùng
    try {
      setAdding(true);
      setErr('');
      await api('/documents', {
        method: 'POST',
        body: JSON.stringify({ title, content }),
      });

      setTitle('');
      setContent('');

      await refresh();
    } catch (error: any) {
      setErr(error.message);
    } finally {
      setAdding(false);
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
        `Đã nhận "${body.title}". Hệ thống đang xử lý nền (trích văn bản, chia chunk, embedding); ` +
          'trạng thái trong danh sách bên dưới sẽ tự cập nhật, bạn không cần chờ ở trang này.'
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

          <button className="primary" disabled={!title.trim() || !content.trim() || adding} onClick={addDoc}>
            {adding ? <Loader2 size={16} className="spin" /> : <Plus size={16} />}
            {adding ? 'Đang index…' : 'Index document'}
          </button>

          <label>Hoặc tải file lên (.pdf, .docx, .xlsx, .pptx, .txt, .md, ảnh .png/.jpg có OCR - tối đa 10 MB)</label>

          <input
            key={fileInputKey}
            type="file"
            accept=".pdf,.docx,.xlsx,.pptx,.txt,.md,.png,.jpg,.jpeg"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />

          <button className="primary" disabled={!file || uploading} onClick={uploadFile}>
            <Upload size={16} />
            {uploading ? 'Đang tải lên...' : 'Upload và index'}
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
        <p className="note">Bạn xem được tài liệu công khai và của nhóm mình. Muốn thêm file của riêng bạn, hãy đính kèm (nút 📎) trong AI Playground; file đó chỉ bạn và quản trị viên thấy, bạn tự xóa được. Tài liệu chung do quản trị viên quản lý.</p>
      )}

      {/* Indexed document list */}
      <Panel title={`Indexed documents (${shownDocs.length}${shownDocs.length !== docs.length ? `/${docs.length}` : ''})`}>
        {canEdit && (
          <div className="scope-filter">
            {([['all', 'Tất cả'], ['private', 'File riêng của người dùng']] as const).map(([key, label]) => (
              <button key={key} className={adminFilter === key ? 'secondary active' : 'secondary'}
                onClick={() => setAdminFilter(key)}>{label}</button>
            ))}
          </div>
        )}
        {!canEdit && (
          <div className="scope-filter">
            {([['all', 'Tất cả'], ['own', 'File của tôi'], ['mine', 'Của nhóm tôi'], ['public', 'Công khai']] as const).map(([k, label]) => (
              <button key={k} className={scopeFilter === k ? 'secondary active' : 'secondary'}
                onClick={() => setScopeFilter(k)}>{label}</button>
            ))}
          </div>
        )}
        {shownDocs.length ? (
          shownDocs.map((doc) => (
            <div key={doc.id}>
              <div className="row">
                <FileText />

                <div>
                  <b>{doc.title}</b>
                  <small>
                    {doc.filename} · {doc.size_bytes ? `${(doc.size_bytes / 1024).toFixed(1)} KB · ` : ''}
                    {new Date(doc.created_at).toLocaleString()}
                  </small>
                  {doc.status === 'failed' && doc.error && <p className="doc-error">{doc.error}</p>}
                  <div>
                    {doc.groups?.length ? (
                      doc.groups.map((g) => <span className="chip" key={g.id}>{g.name}</span>)
                    ) : doc.scope === 'private' || (canEdit && doc.owner_id) ? (
                      <span className="chip private">
                        {doc.mine ? 'Riêng tư: chỉ bạn thấy' : `Riêng tư: của ${doc.owner_email ?? 'người dùng'} (gán nhóm để chia sẻ)`}
                      </span>
                    ) : (
                      <span className="chip public">Công khai (mọi người đã đăng nhập)</span>
                    )}
                  </div>
                </div>

                <StatusBadge status={doc.status} />

                {(canEdit || doc.mine) && doc.status === 'failed' && (
                  <button className="secondary" onClick={() => retryDoc(doc)}>
                    <RefreshCw size={15} />
                    Thử lại
                  </button>
                )}

                <button className="secondary" onClick={() => viewDoc(doc.id)}
                  disabled={loadingDoc || doc.status !== 'processed'}>
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

                {(canEdit || doc.mine) && (
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
          <span id="document-viewer" />
          <div className="row">
            <div>
              <b>{selectedDoc.filename}</b>
              <small>
                Trạng thái: {selectedDoc.status}
                {' · '}
                Số chunks: {selectedDoc.chunks?.length ?? 0}
              </small>
            </div>

            <button className="secondary" onClick={() => { setSelectedDoc(null); setFocusChunk(null); }}>
              Đóng
            </button>
          </div>

          <div className="document-content">
            {selectedDoc.chunks?.length ? (
              selectedDoc.chunks.map((chunk) => (
                <section key={chunk.chunk_index} id={`chunk-${chunk.chunk_index}`}
                  className={chunk.chunk_index === focusChunk ? 'document-chunk focused' : 'document-chunk'}>
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
