// Hints and page introductions in the words of the marketing team (FR-MKT-03). Kept apart from hints.ts so the two
// vocabularies are easy to read side by side; the Hint component looks keys up in both.
export const POST_HINTS = {
  'post.col.DISCUSS': { page: 'posts', label: 'Cột Ý tưởng', what: 'Bài mới nghĩ ra hoặc mới nhận brief, chưa ai làm.', do: 'Giao người và đặt ngày đăng; khi bắt đầu làm, bấm "Bắt đầu làm" trong thẻ.' },
  'post.col.IN_PROGRESS': { page: 'posts', label: 'Cột Đang làm', what: 'Có người đang viết, thiết kế hoặc dựng.', do: 'Xong phần của mình thì bấm "Gửi duyệt" trong thẻ.' },
  'post.col.ACCEPTANCE': { page: 'posts', label: 'Cột Chờ duyệt', what: 'Người làm đã gửi, chờ Project Owner xem.', do: 'Project Owner vào trang Chờ duyệt: Duyệt, hoặc Sửa lại kèm một câu.' },
  'post.col.APPROVED': { page: 'posts', label: 'Cột Đã duyệt', what: 'Bài đã được duyệt, chờ đến ngày đăng.', do: 'Đến ngày, người làm đăng lên kênh, dán link và bấm "Đã đăng" ở từng kênh.' },
  'post.col.DONE': { page: 'posts', label: 'Cột Đã đăng', what: 'Bài đã lên mọi kênh.', do: 'Bài cũ hơn 30 ngày tự ẩn; bật "Cả bài cũ" để xem lại.' },
  'post.urgent': { page: 'posts', label: 'Gấp', what: 'Bài cần làm trước các bài khác.', do: 'Bật khi anh/chị hoặc khách cần gấp; bài Gấp đứng đầu cột và có chấm đỏ trên lịch.' },
  'post.channels': { page: 'posts', label: 'Kênh và ngày đăng', what: 'Một bài có thể lên nhiều kênh, mỗi kênh một ngày riêng. Telegram nhắc người làm 60 phút trước giờ và nhắc cả Project Owner 30 phút sau giờ nếu chưa bấm Đã đăng.', do: 'Thêm kênh, đổi ngày, và bấm "Đã đăng" ở từng kênh khi bài đã lên; dán link bài nếu có. Kênh bật tự đăng thì luồng đăng lo, chỉ cần bài Đã duyệt trước giờ.' },
  'post.add_many': { page: 'posts', label: 'Thêm nhiều bài', what: 'Mỗi dòng là một bài; kênh và ngày bắt đầu chung.', do: 'Dán danh sách tên bài, chọn kênh, chọn ngày đầu tuần; app trải đều các bài theo giờ tốt của kênh.' },
  'post.campaign': { page: 'posts', label: 'Chiến dịch', what: 'Một nhãn để gom các bài cùng đợt (ra mắt bản 5.0, Tết…).', do: 'Gõ tên, lần sau chọn lại từ danh sách; lọc Tuần này theo chiến dịch.' },
  'week.late': { page: 'week', label: 'Trễ', what: 'Bài đã đến ngày đăng mà chưa đánh dấu Đã đăng.', do: 'Mở thẻ: đã đăng thì bấm "Đã đăng", chưa thì đổi ngày.' },
  'week.cell_add': { page: 'week', label: 'Thêm bài trong ô', what: 'Dấu + trong một ô tạo bài với kênh và ngày của ô đó.', do: 'Bấm +, gõ tên bài, chọn người; xong.' },
  'review.send_back': { page: 'review', label: 'Sửa lại', what: 'Trả bài về Đang làm kèm một câu nói cần sửa gì.', do: 'Viết ngắn và cụ thể; câu này hiện trong Thảo luận của thẻ và báo cho người làm.' },
  'meeting.schedule': { page: 'posts', label: 'Đưa vào lịch', what: 'Một dòng biên bản thành một bài ở Ý tưởng, với người và ngày đọc từ biên bản.', do: 'Sửa người hoặc ngày ngay trên dòng nếu biên bản ghi chưa rõ, rồi bấm.' },
  'week.hot_topics': { page: 'week', label: 'Chủ đề nóng tuần', what: 'Điều nhiều nguồn anh/chị theo dõi đang nói tới trong tuần, chấm điểm theo số nguồn, trụ và độ mới; AI tóm hai câu và gợi vài góc.', do: 'Bấm tên để đọc phân tích; "Thành bài" tạo bài ở Ý tưởng kèm link nguồn; "Bỏ" thì chủ đề và các bài tìm thấy không hiện lại.' },
  'week.topic_panel': { page: 'week', label: 'Phân tích chủ đề', what: 'Vì sao đáng nói, hai ba góc có thể viết, kênh gợi ý, điều cần kiểm, và các bài nguồn.', do: 'Chọn một góc rồi Thành bài, hoặc Thành chuỗi để có sẵn bản cho từng kênh ưu tiên của trụ với ngày theo giờ tốt.' },
  'week.refresh_topics': { page: 'week', label: 'Làm mới chủ đề', what: 'AI chạy lại ngay thay vì chờ giờ trong lịch; tối đa ba lần mỗi ngày.', do: 'Bấm khi vừa thêm nguồn hoặc từ khóa và muốn thấy kết quả ngay.' },
  'sources.pillars': { page: 'sources', label: 'Trụ cột nội dung', what: 'Khung AI đọc trước mọi việc: mỗi trụ có một câu mô tả, người đọc, kênh ưu tiên, tỉ lệ tuần, từ khóa và hashtag, bài mẫu, điều tránh.', do: 'Viết như nói với một người mới vào đội; từ khóa là cụm người ta hay viết, hashtag bắt đầu bằng #, dấu sao là ưu tiên quét trước.' },
  'sources.networks': { page: 'sources', label: 'Mạng xã hội', what: 'Kênh nào công cụ quét đọc được cho dự án này. Chỉ bật được kênh CTO đã mở; kênh "chưa có cách" là nền tảng không cho đọc.', do: 'Bật kênh anh/chị muốn nghe; link cụ thể dán ở khối Nguồn.' },
  'sources.rhythm': { page: 'sources', label: 'Nhịp quét và AI', what: 'Công cụ quét bao lâu một lần và AI tóm chủ đề lúc mấy giờ, ngày nào.', do: 'Hai mốc sáng và trưa là đủ cho đa số tuần; mỗi mốc là một lượt AI, trần do CTO đặt.' },
  'sources.agent': { page: 'sources', label: 'Lệnh cho agent của đội', what: 'Các lệnh và câu nhắc để Claude Code hoặc Codex của anh/chị đọc chủ đề nóng, tuần này, bài chờ duyệt, và soạn bản kênh qua Intake.', do: 'Bấm Chép rồi dán vào terminal; chưa nối agent thì tạo token ở Tài khoản & bảo mật trước. Agent không đăng gì và không đổi cài đặt.' },
  'sources.demand': { page: 'sources', label: 'Số tín hiệu mỗi tuần', what: 'Bao nhiêu bài tìm thấy mỗi tuần là đủ; công cụ quét dừng khi đủ gấp rưỡi số này.', do: 'Để 30 khi mới bắt đầu; nhiều hơn chỉ thêm rác.' },
  'post.text': { page: 'posts', label: 'Chữ của bản kênh', what: 'Nội dung đúng cho kênh đó, đếm theo luật kênh: X 280 (bài dài tới 25.000), LinkedIn 3.000, Threads 500.', do: 'Vượt mức ngắn thì đỏ để cân nhắc; vượt mức dài thì không Gửi duyệt được.' },
  'post.short_link': { page: 'posts', label: 'Link rút gọn', what: 'Một link ngắn riêng cho bản kênh này, dẫn về trang đích kèm thẻ nguồn; Intake đếm số người bấm.', do: 'Dán link này vào bài khi đăng thay cho link gốc; số bấm hiện ngay cạnh, mọi kênh cùng một thước.' },
} as const

export const POST_INTROS = {
  posts: { title: 'Trang Bài để làm gì', lines: [
    'Mỗi bài đăng là một thẻ, đi qua năm bước: Ý tưởng, Đang làm, Chờ duyệt, Đã duyệt, Đã đăng.',
    'Mở thẻ để thấy kênh và ngày đăng, link ảnh hay video, thảo luận; các nút trong thẻ nói đúng việc tiếp theo.',
    'Muốn xem theo ngày và kênh thì sang Tuần này.',
  ] },
  week: { title: 'Trang Tuần này để làm gì', lines: [
    'Lưới tuần: hàng là kênh, cột là ngày; mỗi ô là một bài lên kênh đó ngày đó.',
    'Thêm bài bằng nút trên cùng hoặc dấu + trong ô; kéo thẻ để đổi ngày.',
    'Ba con số trên cùng: đã lên lịch, chờ duyệt, trễ.',
  ] },
  review: { title: 'Trang Chờ duyệt để làm gì', lines: [
    'Bài người làm đã gửi, chờ anh/chị xem: tên, người, kênh và ngày, mô tả, link ảnh hay video.',
    'Duyệt thì bài sang Đã duyệt và chờ ngày đăng; Sửa lại thì bài về Đang làm kèm câu anh/chị viết.',
  ] },
  sources: { title: 'Trang Nguồn và trụ để làm gì', lines: [
    'Khai trụ cột nội dung: AI đọc khung này trước khi tóm chủ đề nóng hay đề xuất bài.',
    'Dán nguồn muốn theo dõi, bật mạng xã hội CTO đã mở, đặt giờ AI chạy; công cụ quét bên ngoài đọc các cài đặt này.',
    'Kết quả hiện ở khối Chủ đề nóng tuần trên trang Tuần này.',
  ] },
} as const

export const POST_HINT_PAGES: Record<string, string> = { week: 'Tuần này', posts: 'Bài', review: 'Chờ duyệt', sources: 'Nguồn và trụ' }
