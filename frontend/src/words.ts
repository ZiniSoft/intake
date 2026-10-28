// The words of the marketing team (FR-MKT-03, ADR-0067). The same data is "Việc" on a software board and "Bài" on a
// marketing board; nothing here changes what is stored, only what people read.
import type { WorkItemStatus } from './types'

export type UiMode = 'MARKETING' | 'FULL'

export const POST_COLUMNS: { value: WorkItemStatus; label: string; hint: string }[] = [
  { value: 'DISCUSS', label: 'Ý tưởng', hint: 'Bài mới nghĩ ra hoặc mới nhận brief, chưa ai làm.' },
  { value: 'IN_PROGRESS', label: 'Đang làm', hint: 'Đang viết, thiết kế hoặc dựng.' },
  { value: 'ACCEPTANCE', label: 'Chờ duyệt', hint: 'Người làm đã gửi, chờ Project Owner xem.' },
  { value: 'APPROVED', label: 'Đã duyệt', hint: 'Duyệt rồi, chờ đến ngày đăng.' },
  { value: 'DONE', label: 'Đã đăng', hint: 'Đã lên mọi kênh.' },
]

export const POST_STATUS_LABELS: Record<WorkItemStatus, string> = {
  DISCUSS: 'Ý tưởng', READY: 'Ý tưởng', IN_PROGRESS: 'Đang làm', ACCEPTANCE: 'Chờ duyệt', APPROVED: 'Đã duyệt', DONE: 'Đã đăng', CANCELLED: 'Đã bỏ',
}

// Which column a post stands in on the marketing board: Sẵn sàng has no column there and counts as Ý tưởng.
export function postColumnOf(status: WorkItemStatus): WorkItemStatus {
  return status === 'READY' ? 'DISCUSS' : status
}

export const CHANNEL_NAMES: Record<string, string> = {
  FACEBOOK_PAGE: 'Facebook trang công ty', FACEBOOK_PERSONAL: 'Facebook trang cá nhân', THREADS: 'Threads', X: 'X (Twitter)', LINKEDIN: 'LinkedIn',
  INSTAGRAM: 'Instagram', TIKTOK: 'TikTok', YOUTUBE: 'YouTube', REELS: 'Reels', EMAIL: 'Email', WEBSITE: 'Website', BLOG: 'Blog',
}
export const CHANNEL_SHORT: Record<string, string> = {
  FACEBOOK_PAGE: 'FB', FACEBOOK_PERSONAL: 'FB cá nhân', THREADS: 'Threads', X: 'X', LINKEDIN: 'LinkedIn', INSTAGRAM: 'IG', TIKTOK: 'TikTok', YOUTUBE: 'YouTube',
  REELS: 'Reels', EMAIL: 'Email', WEBSITE: 'Web', BLOG: 'Blog',
}
export const CHANNEL_ORDER = ['FACEBOOK_PAGE', 'FACEBOOK_PERSONAL', 'THREADS', 'X', 'LINKEDIN', 'INSTAGRAM', 'TIKTOK', 'YOUTUBE', 'REELS', 'EMAIL', 'WEBSITE', 'BLOG']
export const FORMAT_LABELS: Record<string, string> = { POST: 'Bài viết', IMAGE: 'Ảnh', VIDEO: 'Video', LONGFORM: 'Bài dài', EMAIL: 'Email' }
export const CHANNEL_VERSION_LABELS: Record<string, string> = { DRAFT: 'Chưa sẵn sàng', READY: 'Sẵn sàng đăng', PUBLISHED: 'Đã đăng' }

export const POST_WORDS = {
  unit: 'Bài', board: 'Bài', week: 'Tuần này', review: 'Chờ duyệt',
  add: 'Thêm bài', addMany: 'Thêm nhiều bài',
  start: 'Bắt đầu làm', submit: 'Gửi duyệt', approve: 'Duyệt', sendBack: 'Sửa lại', publish: 'Đã đăng', drop: 'Bỏ bài', undrop: 'Lấy lại bài',
  noLinkQuestion: 'Chưa có link bài, vẫn đánh dấu đã đăng?',
  sendBackAsk: 'Cần sửa gì? Một câu là đủ, người làm sẽ thấy trong Thảo luận.',
  dropAsk: 'Vì sao bỏ bài này?',
  weekHelper: ['Lưới tuần: hàng là kênh, cột là ngày. Mỗi ô là một bài đi lên kênh đó ngày đó.', 'Kéo thẻ sang ngày khác để đổi lịch, hoặc mở thẻ và đổi ngày. Bấm dấu + trong ô để thêm bài ngay kênh và ngày đó.', 'Ba con số trên cùng: đã lên lịch, chờ duyệt, trễ (đến ngày mà chưa đăng).'],
  boardHelper: ['Mỗi bài qua năm bước: Ý tưởng, Đang làm, Chờ duyệt, Đã duyệt, Đã đăng.', 'Mở thẻ để xem kênh và ngày đăng, link tài sản, thảo luận; các nút trong thẻ nói đúng việc tiếp theo.', 'Bỏ bài nằm ở cuối thẻ, có hỏi lý do.'],
  reviewHelper: ['Bài người làm đã gửi, chờ anh/chị xem.', 'Duyệt thì bài sang Đã duyệt và chờ ngày đăng; Sửa lại thì bài về Đang làm kèm câu anh/chị viết.'],
  // Listening (FR-MKT-08..12): hot topics, the sources page, the words of a version, the short link.
  hotTopics: 'Chủ đề nóng tuần', toPost: 'Thành bài', toSeries: 'Thành chuỗi', dropTopic: 'Bỏ', refreshTopics: 'Làm mới',
  sourcesPage: 'Nguồn và trụ', pillars: 'Trụ cột nội dung', networks: 'Mạng xã hội', rhythm: 'Nhịp quét và AI', agentCommands: 'Lệnh cho agent của đội',
  keptThisWeek: (n: number) => (n === 0 ? 'Chưa chủ đề nào thành bài tuần này' : `${n} chủ đề đã thành bài tuần này`),
  topicsEmpty: 'Chưa có chủ đề. Thêm nguồn và từ khóa ở Nguồn và trụ, công cụ quét sẽ mang tín hiệu về và AI tóm lại mỗi sáng.',
  charCount: (n: number, max: number) => `${n.toLocaleString('vi-VN')} / ${max.toLocaleString('vi-VN')} ký tự`,
  getLink: 'Lấy link', copyLink: 'Chép link', copied: 'Đã chép',
  sourcesHelper: ['Trụ cột là khung AI đọc trước khi tóm chủ đề hay đề xuất bài: tên, một câu mô tả, người đọc, kênh ưu tiên, tỉ lệ tuần, từ khóa và hashtag, bài mẫu, điều tránh.', 'Nguồn là các trang, RSS, kênh anh/chị muốn theo dõi; mạng xã hội chỉ bật được kênh CTO đã mở.', 'Nhịp: công cụ quét bao lâu một lần, AI tóm chủ đề lúc mấy giờ; tất cả nằm trong trần CTO đặt.'],
}

// Monday of the week holding a day (YYYY-MM-DD), and days around it, without time zones getting in the way.
export function mondayOf(day: string): string {
  const d = new Date(`${day}T00:00:00`)
  const diff = (d.getDay() + 6) % 7
  d.setDate(d.getDate() - diff)
  return isoDay(d)
}
export function isoDay(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
export function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00`)
  d.setDate(d.getDate() + n)
  return isoDay(d)
}
// The local day of an ISO timestamp, for placing a channel version on the grid.
export function dayOfStamp(stamp: string | null): string | null {
  if (!stamp) return null
  return isoDay(new Date(stamp))
}
export function timeOfStamp(stamp: string | null): string {
  if (!stamp) return ''
  const d = new Date(stamp)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}
// A local day plus HH:MM as an ISO timestamp with the browser's offset.
export function stampOf(day: string, time: string): string {
  return new Date(`${day}T${time || '09:00'}:00`).toISOString()
}
