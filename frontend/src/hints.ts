import { POST_HINTS, POST_INTROS } from './hints_posts'

// Short explanations for the people who use Intake every day (FR-UI-17). Each hint answers two questions in plain
// Vietnamese: what this is, and what to do with it. The CTO edits this file; a change is one small commit.
// Keys are stable: the audit counts how often each one is opened.

export type HintKey = keyof typeof HINTS | keyof typeof POST_HINTS

export const HINTS = {
  // Bảng Việc
  'work.col.DISCUSS': { page: 'work', label: 'Cột Cần bàn', what: 'Việc chưa quyết làm hay không, hoặc chưa rõ làm thế nào.', do: 'Bàn trong phần Thảo luận của thẻ; rõ rồi thì kéo sang Sẵn sàng.' },
  'work.col.READY': { page: 'work', label: 'Cột Sẵn sàng', what: 'Việc đã rõ, có thể bắt đầu, đang chờ người nhận.', do: 'Project Owner giao người và hạn; người làm kéo sang Đang làm khi bắt đầu.' },
  'work.col.IN_PROGRESS': { page: 'work', label: 'Cột Đang làm', what: 'Việc có người đang làm.', do: 'Xong phần của mình thì kéo sang Chờ nghiệm thu; vướng gì thì ghi vào Thảo luận.' },
  'work.col.ACCEPTANCE': { page: 'work', label: 'Cột Chờ nghiệm thu', what: 'Người làm báo xong, chờ Project Owner xem.', do: 'Project Owner xem kết quả rồi kéo sang Xong, hoặc trả lại Đang làm kèm lý do (lý do tự thành một dòng Thảo luận).' },
  'work.col.DONE': { page: 'work', label: 'Cột Xong', what: 'Việc đã được Project Owner xác nhận, hoặc đã thành Issue trên GitLab.', do: 'Việc Xong hơn 30 ngày tự ẩn; bật "Cả việc Xong và Bỏ" để xem lại.' },
  'work.col.CANCELLED': { page: 'work', label: 'Cột Bỏ', what: 'Việc không làm nữa. Luôn có lý do đi kèm.', do: 'Kéo vào đây thì hệ thống hỏi lý do; đổi ý thì kéo ra lại được.' },
  'work.video_only': { page: 'work', label: 'Chỉ video', what: 'Chỉ hiện các việc có quy trình (mẫu Video) để nhìn tiến độ từng video.', do: 'Bỏ chọn để thấy lại mọi việc.' },
  'work.links': { page: 'work', label: 'Liên kết trên việc', what: 'Nơi việc này "sống" ngoài Intake: thư mục Drive, thiết kế Canva, bản cắt, bài đã đăng. Intake chỉ giữ địa chỉ, không giữ tệp.', do: 'Dán link và một ghi chú ngắn. Link là bằng chứng khi nghiệm thu bước Duyệt và Đăng.' },
  'work.discussion': { page: 'work', label: 'Thảo luận', what: 'Chỗ Project Owner và đội bàn trước khi làm, và ghi lại điều đã chốt.', do: 'Viết cho đội đọc. Không dán tin nhắn hay tên của khách.' },
  'work.steps': { page: 'work', label: 'Các bước', what: 'Sáu bước của một video, mỗi bước là một thẻ con có người làm, hạn, link riêng.', do: 'Đổi cột từng bước ngay tại đây; bấm tên bước để mở thẻ con. Việc mẹ tự Xong khi mọi bước đã đóng.' },
  'work.issue': { page: 'work', label: 'Tạo Issue', what: 'Chuyển việc này thành Issue trên GitLab hoặc GitHub của dự án, để vào kế hoạch ngày và nghiệm thu như việc code.', do: 'Chỉ bấm khi việc đã bàn xong và đủ rõ để làm. Sau khi Issue có, thẻ này sang Xong và theo dõi tiếp ở Issue.' },
  'work.column_pick': { page: 'work', label: 'Đổi cột', what: 'Cột là trạng thái của việc.', do: 'Chọn cột ở đây hoặc kéo thẻ trên bảng. Bỏ và trả lại từ Chờ nghiệm thu cần ghi lý do.' },
  'work.template': { page: 'work', label: 'Mẫu quy trình', what: 'Mẫu Video tạo sẵn sáu bước: Brief, Kịch bản, Quay, Dựng, Duyệt, Đăng.', do: 'Chọn khi việc là một video; bước Duyệt và Đăng chỉ Xong khi có link bản cắt hoặc bài đã đăng.' },
  // Việc của tôi
  'myday.status': { page: 'my_day', label: 'Trạng thái việc', what: 'Bạn báo việc đang làm, xong hay bị chặn; Project Owner và CTO nhìn thấy ngay.', do: 'Đặt Đang làm khi bắt đầu. Xong với việc có Issue thì hỏi bằng chứng: link commit, MR, hoặc tài liệu.' },
  'myday.plan_open': { page: 'my_day', label: 'Kế hoạch chưa chốt', what: 'Project Owner chưa duyệt kế hoạch ngày; việc có thể còn đổi.', do: 'Vẫn làm được; nếu việc đổi, bạn sẽ thấy ở đây.' },
  'myday.propose': { page: 'my_day', label: 'Đề xuất việc', what: 'Muốn làm một việc chưa có trong kế hoạch: nêu số Issue, mã Intake hoặc mô tả, kèm giờ.', do: 'Đề xuất vào "Việc chờ phân công"; Project Owner xếp hoặc bỏ qua.' },
  // Góp ý
  'feedback.new': { page: 'feedback', label: 'Góp ý mới', what: 'Một điều dự án nên làm, bằng lời của bạn, có thể kèm ảnh. Chưa phải yêu cầu chính thức.', do: 'Project Owner đọc và "Nhận" thì nó thành Intake và AI đọc; "Từ chối" thì bạn nhận một dòng lý do.' },
  // Tài khoản và agent
  'account.token': { page: 'account', label: 'Token cho agent', what: 'Chìa khóa để Claude Code, Codex hay luồng tự động gọi Intake với đúng quyền của bạn.', do: 'Tạo một token mỗi máy, chép ngay vì chỉ hiện một lần; mất thì thu hồi và tạo cái mới.' },
  'account.commands': { page: 'account', label: 'Lệnh cho agent', what: 'Các lệnh ngắn trong terminal: /in-today lấy việc hôm nay, /in-content-day việc trên bảng, /in-end-day soạn báo cáo cuối ngày.', do: 'Cài một lần mỗi máy bằng dòng cài; sau đó gõ lệnh trong Claude Code hoặc Codex.' },
} as const

export type PageIntroKey = keyof typeof PAGE_INTROS | keyof typeof POST_INTROS

export const PAGE_INTROS = {
  work: { title: 'Trang Việc để làm gì', lines: [
    'Mỗi dự án có một bảng việc nội bộ: việc không phải code, hoặc việc cần bàn trước khi thành Issue.',
    'Kéo thẻ qua sáu cột từ Cần bàn đến Xong; bấm thẻ để xem mô tả, link, thảo luận và lịch sử.',
    'Video có mẫu sáu bước; bước Duyệt và Đăng cần link bản cắt hoặc bài đã đăng mới Xong.',
  ] },
  my_day: { title: 'Trang Việc của tôi để làm gì', lines: [
    'Việc Project Owner xếp cho bạn trong ngày, ưu tiên cao trước.',
    'Đặt Đang làm khi bắt đầu, Xong khi xong (có Issue thì kèm bằng chứng), Bị chặn khi vướng.',
    'Cuối ngày gửi báo cáo ngày; trong terminal gõ /in-end-day để agent soạn từ commit.',
  ] },
  feedback: { title: 'Trang Góp ý để làm gì', lines: [
    'Nói điều dự án nên làm, bằng lời của bạn, có thể kèm ảnh. Chưa phải yêu cầu chính thức.',
    'Project Owner nhận thì góp ý thành Intake và AI đọc; từ chối thì bạn nhận một dòng lý do.',
    'Không ghi tên khách, số điện thoại hay tin nhắn thật; mô tả bằng lời.',
  ] },
  account: { title: 'Trang Tài khoản và agent để làm gì', lines: [
    'Đổi mật khẩu, bật xác thực hai lớp, và tạo token để agent trong terminal gọi Intake như bạn.',
    'Token chỉ hiện một lần: chép ngay, mỗi máy một token, mất thì thu hồi.',
    'Lệnh ngắn cho agent (/in-today, /in-content-day, /in-end-day, /in-hot-topics, /in-draft-post) ở menu tài khoản, mục "Lệnh cho agent".',
  ] },
} as const

export const HINT_PAGES: Record<string, string> = { work: 'Việc', my_day: 'Việc của tôi', feedback: 'Góp ý', account: 'Tài khoản và agent' }
export const ALL_HINTS: Record<string, { page: string; label: string; what: string; do: string }> = { ...HINTS, ...POST_HINTS }
export const ALL_INTROS: Record<string, { title: string; lines: readonly string[] }> = { ...PAGE_INTROS, ...POST_INTROS }
