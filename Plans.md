# Plans — Nhóm B: Tài khoản và quản trị

Purpose: Đưa hệ thống tài khoản (đăng ký/đăng nhập/phân quyền admin) vào sản
phẩm tự luyện, và **gắn chủ sở hữu thật** cho `self_practice_sessions` — hiện
mọi endpoint mở cho bất kỳ ai có session id. Phạm vi: Task 10-13 của
`specs/in-class-analysis/tasks.md`. Task 14 (bảng theo dõi chất lượng) phụ
thuộc `PeerNote` từ Nhóm C, **blocked**, không nằm trong Plans này.

Spec: `specs/in-class-analysis/plan.md` (mục "Đăng ký, đăng nhập và phân
quyền", đã cập nhật thêm phần "Gắn chủ sở hữu vào phiên tự luyện" cho Plans
này) + `specs/in-class-analysis/tasks.md` Task 10-13. (Cả hai file nằm trong
`specs/`, bị gitignore theo chủ đích đã xác nhận với người dùng — không phải
thiếu sót.)

team_validation_mode: `manual-pass` — không dùng Task tool spawn 5 subagent
riêng cho non-trivial planning gate (auth/data-model/permissions đúng là
non-trivial), tự đánh giá 5 góc nhìn dưới đây thay vì phân tách agent, vì đây
là một luồng auth CRUD tiêu chuẩn, rủi ro/độ mới thấp, không cần chi phí đó.

- **Product**: đúng đề bài — đăng ký xong dùng ngay, không hàng đợi, không
  chọn vai trò; admin chỉ tạo bằng CLI. Khớp `plan.md`.
- **Architecture**: tái dùng đúng pattern đã có (`db/models.py` + Alembic
  hand-written, `routers/*.py` + `Depends`, JWT qua `Authorization: Bearer`).
  Không thêm framework auth mới (không Auth0/Clerk) — quá tay cho quy mô này.
- **Security**: bcrypt (đã đúng thư viện dùng ở nơi khác trong repo cho các
  dự định trước), JWT ký HS256 với secret từ env, không log token/mật khẩu,
  password tối thiểu ràng buộc độ dài ở cả hai phía.
- **QA**: mỗi task có DoD kiểm được bằng lệnh cụ thể (không dùng tính từ mơ
  hồ); test ownership phải bao gồm case `user_id IS NULL` (phiên cũ) và case
  hai tài khoản khác nhau.
- **Skeptic**: rủi ro lớn nhất không phải là viết auth (chuẩn, đã làm nhiều
  nơi) mà là **quên áp ownership check vào một endpoint** — do đó Task B4 bắt
  buộc liệt kê từng route trong `routers/self_practice.py` và kiểm từng route
  trong DoD, không kiểm gộp.

## Quyết định đã chốt (bạn có thể yêu cầu đổi trước khi bắt đầu B1)

- **Không xác minh email.** Khớp nguyên tắc đã có "đăng ký xong vào dùng được
  ngay, không hàng đợi duyệt".
- **JWT lưu ở `localStorage` phía frontend**, không dùng httpOnly cookie.
  Đơn giản hơn, khớp mức độ một sản phẩm tự luyện MVP hiện tại; đánh đổi là
  rủi ro XSS đọc được token — ghi vào `plan.md` mục "Rủi ro đã biết" ở cuối
  Plans này thay vì âm thầm bỏ qua.
- **Thời hạn token: 7 ngày**, không có refresh token ở đợt này (thêm sau nếu
  cần).

## Plans

| Task | Nội dung | DoD | Depends | Status |
|---|---|---|---|---|
| B1 | [tdd:required] `UserORM` + migration `0010`: `id`, `email` (unique), `password_hash`, `full_name`, `is_admin` (default false), `is_active` (default true), `created_at`, `last_login_at`. Cùng migration: `self_practice_sessions.user_id` (FK `users.id`, nullable). `utils/security.py`: `hash_password`/`verify_password` (bcrypt, muối per-password qua `bcrypt.gensalt()`), `create_access_token`/`decode_access_token` (JWT HS256, secret từ `settings.JWT_SECRET_KEY`, hạn 7 ngày). | `pytest tests/test_security.py` xanh: hash hai lần cùng mật khẩu ra hai chuỗi khác nhau, `verify_password` đúng/sai chính xác; token hết hạn/sai chữ ký bị `decode_access_token` từ chối. `\d users` (hoặc tương đương SQLAlchemy inspect) không có cột `role`. | - | cc:完了 (chưa commit — chờ người dùng duyệt commit theo quy định phiên) |
| B2 | [tdd:required] `routers/auth.py`: `POST /auth/register` (email+password+full_name, validate định dạng email + độ dài mật khẩu tối thiểu 8 ký tự ở cả model Pydantic lẫn frontend form, trả JWT ngay — không hàng đợi), `POST /auth/login`, `POST /auth/change-password` (yêu cầu mật khẩu cũ đúng). Cập nhật `last_login_at` khi login. | `pytest tests/test_auth_api.py` xanh: đăng ký → nhận JWT hợp lệ ngay (không cần bước xác nhận nào khác); đăng ký trùng email → 409; sai mật khẩu lúc login → 401; đổi mật khẩu bằng mật khẩu cũ sai → 401, đúng → đăng nhập lại bằng mật khẩu mới thành công. | B1 | cc:WIP |
| B3 | [tdd:required] `Depends` dùng chung kiểm `is_admin` — **đọc lại `is_admin` từ DB theo `user_id` trong token ở mỗi request, không tin giá trị `is_admin` trong payload token** (xem "Quyết định bổ sung từ advisor consult"). 401 nếu không có token hợp lệ, 403 nếu tài khoản không phải admin. `scripts/create_admin.py`: CLI nhận email có sẵn, set `is_admin=true` (không tạo tài khoản mới nếu email không tồn tại — báo lỗi rõ ràng). Không có endpoint đăng ký admin. | `pytest` xanh: gọi route gắn `Depends(require_admin)` bằng token thường → 403; bằng token admin → 200; không token → 401; token admin phát hành trước khi bị gỡ `is_admin` → gọi lại nhận 403 ngay (không cần đợi token hết hạn). `python -m scripts.create_admin --email ...` set đúng cờ, chạy lại trên email không tồn tại thoát mã lỗi khác 0. | B1 | cc:TODO |
| B4 | [tdd:required] Áp JWT bắt buộc + kiểm sở hữu vào **từng** route của `routers/self_practice.py`: `POST /self-practice` (gắn `user_id` từ token vào session mới), `GET /self-practice` (chỉ liệt kê phiên của chính mình, trừ admin thấy hết), `GET /self-practice/{id}`, `GET /self-practice/{id}/video`, `DELETE /self-practice/{id}`, `POST/PATCH/DELETE .../notes/...`. Quy tắc: `session.user_id IS NULL` → chỉ admin truy cập được; `session.user_id` khác token → 403; khớp hoặc là admin → cho qua. | `pytest tests/test_self_practice_api.py` (mở rộng) xanh: viết lại test hiện có để đăng nhập trước; thêm test hai tài khoản A/B — B gọi bất kỳ route nào trên phiên của A đều nhận 403; phiên tạo trước khi có tài khoản (`user_id NULL`, ví dụ set trực tiếp trong test fixture) chỉ admin gọi được, tài khoản thường nhận 403. Test riêng từng route, không gộp một test "tất cả route đều chặn". | B1, B2 | cc:TODO |
| B5 | [tdd:skip:ui-behavior-covered-by-manual-check] Frontend: `pages/Login.tsx`, `pages/Register.tsx`; JWT lưu `localStorage`, gắn `Authorization: Bearer` vào mọi request `lib/api.ts`; route `/app/*` chuyển hướng `/login` nếu chưa đăng nhập; `Navbar.tsx` thêm nút đăng xuất. | `npm run build` sạch; thử thủ công: chưa đăng nhập vào `/app` bị đẩy về `/login`; đăng ký → vào thẳng `/app`; đăng xuất → gọi lại API tự luyện trả 401 và bị đẩy về `/login`. | B2 | cc:TODO |
| B6 | [tdd:skip:read-only-admin-screen] `pages/AdminUsers.tsx` (route `/app/admin/users`, chỉ hiện khi `is_admin`): danh sách + tìm kiếm theo email, khoá/mở khoá qua `is_active`. `routers/admin.py`: `GET /admin/users`, `PATCH /admin/users/{id}` (chỉ đổi `is_active`, không có xoá). **Khoá có hiệu lực ngay với token đang sống**: dependency xác thực đọc `is_active` từ DB mỗi request (xem "Quyết định bổ sung từ advisor consult"). | `pytest` xanh: khoá tài khoản (`is_active=false`) → tài khoản đó login trả 401 với thông báo rõ (không nhầm với sai mật khẩu), **và token đã phát hành trước khi khoá gọi API tự luyện cũng nhận 401 ngay**; lịch sử `self_practice_sessions` của tài khoản đó vẫn còn nguyên trong DB sau khi khoá. | B3 | cc:TODO |

Task 14 (bảng theo dõi chất lượng): **blocked** — phụ thuộc `PeerNote` (Nhóm
C), chưa tồn tại. Không đưa vào Plans này.

## Quyết định bổ sung từ advisor consult (trước khi làm B1)

- **Email so khớp không phân biệt hoa/thường**: unique index trên
  `lower(email)`, chuẩn hoá về chữ thường ở tầng service trước khi lưu/so
  khớp — không dùng extension `citext` của Postgres để tránh thêm phụ thuộc.
- **Mật khẩu dài hơn 72 byte UTF-8 bị từ chối rõ ràng** (giới hạn cứng của
  bcrypt — im lặng cắt bớt là hành vi sai, không phải giới hạn cần chấp nhận).
- **`decode_access_token` luôn truyền `algorithms=["HS256"]` tường minh** cho
  `jwt.decode`, không dựa vào giá trị mặc định của thư viện.
- **`is_admin` trong JWT chỉ là ảnh chụp lúc phát hành, không phải nguồn sự
  thật.** Token sống 7 ngày; nếu B3 (`require_admin`) hay B6 (khoá tài khoản
  qua `is_active`) chỉ đọc từ payload token, thu hồi quyền admin hoặc khoá
  tài khoản sẽ không có hiệu lực cho tới khi token hết hạn. **Chốt ngay từ
  B1**: B3/B6 phải đọc lại `is_admin`/`is_active` từ DB theo `user_id` trong
  token ở mỗi request, token chỉ dùng để định danh `user_id`, không dùng để
  quyết định quyền truy cập. Đánh dấu B3/B6 để không quên khi tới lượt làm.

## 事前確認 (Pre-approval)

Không có secret-read (JWT secret đọc từ biến môi trường lúc runtime như mọi
setting khác trong `config.py`, không phải đọc để hiển thị), không có
external-send mới ngoài `git push` đã có sẵn cơ chế xin phép riêng (chỉ
commit/push khi người dùng bảo — quy định đã chốt từ trước, Plans này không
đổi quy định đó), không có thao tác phá huỷ (`user_id` là cột mới, nullable,
không sửa/xoá dữ liệu hiện có).

- Thêm biến môi trường mới `JWT_SECRET_KEY` vào `.env.example` (giá trị mẫu,
  không phải secret thật) — không phải secret-read, chỉ khai báo tên biến.

## Sau khi Plans này được duyệt

新しいセッションの起動コマンド: `claude`
起動後の最初の入力: `/harness-work B1`
向いている場面: B1 không phụ thuộc gì, và B2-B4 đều phụ thuộc B1 — làm tuần
tự từ B1 là đường an toàn nhất cho một luồng auth có thứ tự phụ thuộc rõ
(B1 → B2/B3 → B4 → B5/B6), không phù hợp chạy song song `/breezing all` vì
rủi ro bỏ sót ownership check (đúng lo ngại ở góc nhìn Skeptic phía trên) nếu
B4 làm trước khi B1/B2 xong.
