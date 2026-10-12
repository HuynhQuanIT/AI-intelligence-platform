import type { Access } from '../types';

// Chip tên nhóm của người dùng (dùng ở thanh bên và trang tài khoản).
export function GroupChips({ access }: { access?: Access }) {
  const groups = access?.groups ?? [];
  if (!groups.length) return null;
  return (
    <div className="my-groups">
      {groups.map((g) => (
        <span className="chip" key={g.id} title={g.description || g.name}>{g.name}</span>
      ))}
    </div>
  );
}

// Một dòng tóm tắt quyền xem tài liệu, dùng trong AI Playground.
export function AccessLine({ access }: { access?: Access }) {
  if (!access) return null;
  const names = access.groups.map((g) => g.name).join(', ');
  return (
    <p className="access-line">
      Chatbot đang dùng {access.visible_documents} tài liệu cho bạn
      {access.groups.length ? ` (${access.group_documents} thuộc nhóm ${names})` : ''}
    </p>
  );
}
