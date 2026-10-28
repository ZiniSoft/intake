import { createContext, ReactNode, useContext, useMemo, useState } from 'react'

// Sample data and a signed-in person, kept in memory so the example pages work without a server.
// In a real project this file is replaced by calls to the API. Names and titles here are data, not interface text,
// so they are not in the dictionaries.
export type RequestStatus = 'new' | 'waiting' | 'approved' | 'rejected'
export type Request = { id: string; code: string; title: string; project: string; from: string; receivedAt: string; status: RequestStatus; original: string; summary: string; owner?: string }
export type Member = { id: string; name: string; email: string; role: 'member' | 'lead'; active: boolean }
export type Project = { id: string; code: string; name: string; kind: 'software' | 'content'; lead: string }
export type TimeOffStatus = 'waiting' | 'approved' | 'declined'
// startDate is a calendar day, "YYYY-MM-DD", with no time and no time zone.
export type TimeOff = { id: string; member: string; startDate: string; days: number; reason: string; status: TimeOffStatus }
export type Session = { name: string; email: string; mustChangePassword: boolean }

const seedRequests: Request[] = [
  { id: 'r1', code: 'POR-2610-004', title: 'Khách không nhận được mã xác nhận khi đăng nhập', project: 'Cổng khách hàng', from: 'Zalo', receivedAt: '2026-10-06T08:40:00+07:00', status: 'waiting', owner: 'An Nguyễn',
    original: 'Anh ơi sáng nay 3 khách báo bấm đăng nhập xong không thấy mã gửi về điện thoại, chờ 5 phút cũng không có. Bên em kiểm tra giúp với ạ.',
    summary: 'Ba khách hàng không nhận được mã xác nhận qua tin nhắn khi đăng nhập sáng 06/10. Cần kiểm tra dịch vụ gửi tin.' },
  { id: 'r2', code: 'POR-2610-003', title: 'Thêm bộ lọc theo ngày ở trang hóa đơn', project: 'Cổng khách hàng', from: 'Email', receivedAt: '2026-10-05T15:10:00+07:00', status: 'waiting',
    original: 'Chị muốn xem hóa đơn theo tháng, hiện giờ phải kéo rất dài mới tìm được.',
    summary: 'Khách muốn lọc danh sách hóa đơn theo khoảng ngày.' },
  { id: 'r3', code: 'NOI-2610-002', title: 'Bài giới thiệu tính năng mới cho bản tin tháng 10', project: 'Nội dung', from: 'Họp', receivedAt: '2026-10-04T10:00:00+07:00', status: 'approved', owner: 'Chi Trần',
    original: 'Trong họp tuần: cần một bài 600 chữ giới thiệu trang hóa đơn mới, gửi kèm bản tin ngày 15.',
    summary: 'Viết bài 600 chữ giới thiệu trang hóa đơn mới cho bản tin ngày 15/10.' },
  { id: 'r4', code: 'POR-2610-001', title: 'Đổi màu nút thanh toán', project: 'Cổng khách hàng', from: 'Zalo', receivedAt: '2026-10-02T09:20:00+07:00', status: 'rejected',
    original: 'Nút thanh toán nên màu xanh lá cho dễ thấy.', summary: 'Đề nghị đổi màu nút thanh toán sang xanh lá.' },
  { id: 'r5', code: 'POR-2610-005', title: 'Trang hồ sơ tải chậm trên điện thoại', project: 'Cổng khách hàng', from: 'Email', receivedAt: '2026-10-06T09:05:00+07:00', status: 'new',
    original: 'Mở trang hồ sơ trên điện thoại mất gần 10 giây.', summary: '' },
]
const seedMembers: Member[] = [
  { id: 'm1', name: 'An Nguyễn', email: 'an@congty.vn', role: 'lead', active: true },
  { id: 'm2', name: 'Bình Lê', email: 'binh@congty.vn', role: 'member', active: true },
  { id: 'm3', name: 'Chi Trần', email: 'chi@congty.vn', role: 'lead', active: true },
  { id: 'm4', name: 'Dũng Phạm', email: 'dung@congty.vn', role: 'member', active: false },
]
const seedProjects: Project[] = [
  { id: 'p1', code: 'POR', name: 'Cổng khách hàng', kind: 'software', lead: 'An Nguyễn' },
  { id: 'p2', code: 'NOI', name: 'Nội dung', kind: 'content', lead: 'Chi Trần' },
]
const seedTimeOff: TimeOff[] = [
  { id: 't1', member: 'Bình Lê', startDate: '2026-10-12', days: 2, reason: 'Về quê dự đám cưới em gái.', status: 'waiting' },
  { id: 't2', member: 'Chi Trần', startDate: '2026-10-20', days: 1, reason: 'Khám sức khỏe định kỳ.', status: 'waiting' },
  { id: 't3', member: 'An Nguyễn', startDate: '2026-10-08', days: 3, reason: 'Đưa gia đình đi Đà Lạt.', status: 'approved' },
  { id: 't4', member: 'Dũng Phạm', startDate: '2026-09-29', days: 5, reason: 'Nghỉ chăm con mới sinh.', status: 'approved' },
  { id: 't5', member: 'Bình Lê', startDate: '2026-10-15', days: 4, reason: 'Đi du lịch cùng bạn.', status: 'declined' },
]
const SESSION_KEY = 'ui.session'

type Store = {
  session: Session | null
  signIn: (email: string, password: string) => 'ok' | 'wrong'
  setOwnPassword: () => void
  signOut: () => void
  requests: Request[]
  decide: (id: string, status: 'approved' | 'rejected') => void
  members: Member[]
  saveMember: (member: Omit<Member, 'id'> & { id?: string }) => void
  removeMember: (id: string) => void
  projects: Project[]
  addProject: (project: Omit<Project, 'id'>) => void
  timeOff: TimeOff[]
  addTimeOff: (entry: Omit<TimeOff, 'id' | 'status'>) => void
  decideTimeOff: (id: string, status: 'approved' | 'declined') => void
  removeTimeOff: (id: string) => void
}
const StoreContext = createContext<Store | null>(null)

export function StoreProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(() => JSON.parse(sessionStorage.getItem(SESSION_KEY) || 'null') as Session | null)
  const [requests, setRequests] = useState(seedRequests)
  const [members, setMembers] = useState(seedMembers)
  const [projects, setProjects] = useState(seedProjects)
  const [timeOff, setTimeOff] = useState(seedTimeOff)
  const keep = (next: Session | null) => { sessionStorage.setItem(SESSION_KEY, JSON.stringify(next)); setSession(next) }
  const store = useMemo<Store>(() => ({
    session,
    // The sample accepts any email. The password "sai" shows the error state and "tam" the forced password change.
    signIn: (email, password) => {
      if (password === 'sai') return 'wrong'
      keep({ name: 'An Nguyễn', email, mustChangePassword: password === 'tam' })
      return 'ok'
    },
    setOwnPassword: () => { if (session) keep({ ...session, mustChangePassword: false }) },
    signOut: () => keep(null),
    requests,
    decide: (id, status) => setRequests((all) => all.map((request) => (request.id === id ? { ...request, status } : request))),
    members,
    saveMember: (member) => setMembers((all) => (member.id ? all.map((entry) => (entry.id === member.id ? { ...entry, ...member, id: entry.id } : entry)) : [...all, { ...member, id: `m${Date.now()}` }])),
    removeMember: (id) => setMembers((all) => all.filter((member) => member.id !== id)),
    projects,
    addProject: (project) => setProjects((all) => [...all, { ...project, id: `p${Date.now()}` }]),
    timeOff,
    // A new entry always waits for approval and is listed first.
    addTimeOff: (entry) => setTimeOff((all) => [{ ...entry, id: `t${Date.now()}`, status: 'waiting' }, ...all]),
    decideTimeOff: (id, status) => setTimeOff((all) => all.map((entry) => (entry.id === id ? { ...entry, status } : entry))),
    removeTimeOff: (id) => setTimeOff((all) => all.filter((entry) => entry.id !== id)),
  }), [session, requests, members, projects, timeOff])
  return <StoreContext.Provider value={store}>{children}</StoreContext.Provider>
}

export function useStore() {
  const store = useContext(StoreContext)
  if (!store) throw new Error('useStore must be used inside StoreProvider')
  return store
}
