# Kế hoạch quay theo bản voice ElevenLabs

## Thông số bản thu

- Thời lượng: 53,76 giây
- Định dạng: WAV PCM
- Sample rate: 48 kHz
- Bit depth: 16-bit
- Kênh âm thanh: mono
- File nguồn được giữ ngoài repository vì chứa dữ liệu giọng cá nhân.

## Timeline cảnh quay

| Thời gian | Hình ảnh | Thao tác cần quay |
| --- | --- | --- |
| 00:00,00-00:03,85 | Opening card | Hiện logo Intake và dòng `From request to traceable work`. |
| 00:03,85-00:10,50 | Yêu cầu ban đầu | Mở form tạo yêu cầu và dán nội dung demo đã chuẩn bị. Không nhập chậm từng ký tự. |
| 00:11,10-00:16,05 | Kết quả chuẩn hóa | Chuyển sang màn hình kết quả AI và cho thấy cấu trúc công việc đã được tạo. |
| 00:16,65-00:21,90 | Các trường do AI đề xuất | Di chuyển con trỏ qua title, summary, priority và acceptance criteria. |
| 00:22,50-00:31,50 | Human review | Sửa priority hoặc acceptance criterion, sau đó bấm `Approve`. |
| 00:32,10-00:34,80 | GitHub sync | Hiện trạng thái đồng bộ thành công rồi mở GitHub Issue đã tạo. |
| 00:34,80-00:37,85 | Daily Planning | Chuyển sang kế hoạch ngày và làm nổi bật công việc vừa được duyệt. |
| 00:38,35-00:44,40 | Request Journey | Hiện chuỗi `Submitted -> AI proposed -> Human approved -> GitHub synced -> Planned`. |
| 00:44,90-00:53,76 | End card | Lần lượt hiện `AI proposes.`, `People decide.`, `Every step stays traceable.` và địa chỉ repository. |

## Nội dung yêu cầu demo

```text
Customer export fails when the report contains more than 10,000 records.
Please investigate and provide a safer export option.
```

## Kết quả AI cần chuẩn bị trước

```text
Title:
Support large report exports

Priority:
High

Summary:
Large reports fail when the export exceeds 10,000 records.

Acceptance criteria:
- Large exports complete without blocking the user interface.
- The user can see export progress.
- Failed exports provide a clear retry option.
```

Trong cảnh human review, đổi priority từ `High` thành `Medium` để cho thấy AI chỉ đề xuất và con người là người quyết định.

## Cách quay

1. Tạo project video 1920 x 1080, 30 fps và audio 48 kHz.
2. Đưa file voice lên track âm thanh đầu tiên và khóa track này.
3. Quay từng cảnh riêng theo timeline, không quay toàn bộ luồng trong một lần.
4. Đặt các clip hình ảnh lên trên voice rồi cắt theo khoảng nghỉ giữa các câu.
5. Import `captions.elevenlabs.en.vtt` và kiểm tra lại vị trí phụ đề.
6. Giữ con trỏ chuột di chuyển chậm, không rung và không che nội dung chính.
7. Nếu dùng nhạc nền, đặt nhỏ hơn voice khoảng 20-25 dB.
8. Xuất H.264 MP4, 1080p, 30 fps, bitrate video 10-16 Mbps và AAC 48 kHz.

## Kiểm tra trước khi xuất bản

- Chỉ sử dụng project, người dùng và repository demo.
- Không để lộ email, token, notification hoặc dữ liệu khách hàng.
- Kiểm tra phụ đề không che nút hoặc thông tin quan trọng.
- Nghe lại bằng tai nghe và loa máy tính.
- Xem toàn bộ video một lần sau khi xuất MP4.
