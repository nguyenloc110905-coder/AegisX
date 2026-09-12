# AegisX Local Telemetry Journal Foundation Design

Date: 2026-09-12  
Status: approved direction; specification for implementation review

## 1. Mục tiêu dễ hiểu

Hiện tại agent dùng SQLite `outbox.sqlite3` như một hàng chờ: Event được giữ tạm khi chưa gửi được,
nhưng bị xóa khỏi hàng chờ sau khi PostgreSQL xác nhận. Vì vậy máy endpoint không còn lịch sử local
để điều tra.

Milestone này nâng SQLite thành **local telemetry journal**:

- mỗi Event do agent tạo được ghi bền vững ở máy endpoint trước khi gửi mạng;
- trạng thái gửi Event được quản lý cùng transaction với bản ghi local;
- Event đã gửi thành công vẫn còn trong journal cho tới khi hết retention;
- CLI cho người dùng xem dung lượng, kiểm tra hash chain và preview retention;
- Detection/Correlation/Incident phía server tiếp tục hoạt động không đổi trong milestone này.

Nói ngắn gọn: journal là “sổ lịch sử”, còn delivery queue là “danh sách những trang chưa gửi”. Hai
vai trò khác nhau nhưng cùng nằm trong một SQLite database để tránh crash giữa hai lần ghi.

## 2. Phạm vi theo từng lát cắt

### Milestone này — Local Journal Foundation

- lưu local tất cả `NormalizedEvent` mà collector hiện tại thực sự phát ra;
- delivery state, retry, quarantine và acknowledgement nguyên tử;
- retention local, giới hạn dung lượng logic và kiểm tra toàn vẹn;
- CLI `aegisx local-data-status`, `aegisx local-verify`,
  `aegisx local-prune --dry-run`, `aegisx local-prune --apply --yes`;
- migration an toàn từ schema outbox hiện tại;
- server sync policy không đổi: Event đang được gửi lên server vẫn tiếp tục được gửi.

“Tất cả Event agent phát ra” không có nghĩa là kernel telemetry realtime đầy đủ. Resource/network
snapshot vẫn tắt mặc định, và polling vẫn có thể bỏ lỡ hoạt động ngắn giữa hai lần quét.

### Milestone kế tiếp — Selective Sync

Chỉ bắt đầu sau khi người dùng kiểm tra local journal. Milestone đó mới quyết định loại Event nào chỉ
ở local, loại nào luôn lên server, và cách upload cửa sổ bằng chứng trước/sau Detection.

### Milestone tương lai — Realtime và Response

eBPF/kernel event collection, local Detection, signed Decision Policy và privileged Response Executor
là các milestone riêng. Foundation hiện tại không block process, connection hay endpoint.

## 3. Các khái niệm

- **Observation:** điều collector vừa nhìn thấy từ hệ điều hành.
- **NormalizedEvent:** Observation đã có UUID, UTC timestamp và schema version.
- **Journal Event:** bản sao bất biến của NormalizedEvent được lưu trên endpoint.
- **Delivery state:** `PENDING`, `ACKED` hoặc `QUARANTINED`; đây là trạng thái vận chuyển, không phải
  kết luận an ninh.
- **Priority:** lớp retention của Event, không phải severity và không phải xác suất malware.
- **Hash chain:** mỗi bản ghi chứa hash của bản ghi trước. Nó giúp phát hiện mất/sửa đoạn lịch sử,
  nhưng không chống được tuyệt đối attacker đã có root và có thể viết lại cả database lẫn state.
- **Coverage gap:** khoảng thời gian agent biết rằng telemetry có thể đã bị mất vì local storage đầy
  hoặc journal không ghi được. Khoảng trống phải được báo rõ, không được giả vờ hệ thống vẫn quan sát
  đầy đủ.

## 4. Kiến trúc được chọn

```text
Collectors
    -> normalize
    -> LocalTelemetryStore transaction
         1. append immutable journal Event
         2. enqueue Event for delivery
    -> API delivery
         accepted/duplicate -> ACKED + dequeue in one transaction
         permanent invalid  -> QUARANTINED + dequeue in one transaction
         transient failure  -> keep PENDING
    -> server Event -> Detection -> CorrelationCandidate -> Incident
```

Không dùng hai SQLite database cho journal và outbox vì không thể đảm bảo một power loss sẽ commit cả
hai file cùng nhau. Database hiện tại tiếp tục ở
`$AEGISX_AGENT_STATE_DIR/outbox.sqlite3` để upgrade tại chỗ, nhưng code-facing abstraction đổi thành
`LocalTelemetryStore`. Tên file cũ được giữ để migration không cần copy/xóa evidence.

`outbox.py` giữ compatibility import trong một chu kỳ release và delegate sang store mới. Business
logic mới không được thêm tiếp vào wrapper này.

## 5. Ai là nguồn dữ liệu có thẩm quyền

Trong milestone này:

- local journal là bản lịch sử endpoint cho mọi Event agent đã tạo;
- PostgreSQL vẫn là nguồn có thẩm quyền cho Event đã sync và toàn bộ Detection, Candidate, Incident;
- delivery state không làm thay đổi nội dung evidence;
- cùng một Event UUID ở local và server phải có cùng immutable envelope/payload.

Sau selective sync, local journal sẽ là nguồn cho raw telemetry không được gửi. PostgreSQL chỉ có thể
kết luận trên evidence mà nó thực sự nhận; UI/API không được ngụ ý server có visibility đầy đủ khi có
sequence gap hoặc endpoint stale.

## 6. SQLite schema version 2

`PRAGMA user_version = 2` đánh dấu schema.

### `local_events`

| Column | Meaning |
|---|---|
| `sequence INTEGER PRIMARY KEY AUTOINCREMENT` | thứ tự ghi local, tăng đơn điệu |
| `chain_sequence INTEGER NOT NULL` | thứ tự liên tục bên trong priority chain |
| `event_id TEXT NOT NULL UNIQUE` | UUID của NormalizedEvent |
| `schema_version INTEGER NOT NULL` | schema Event |
| `event_type TEXT NOT NULL` | tên evidence |
| `event_timestamp TEXT NOT NULL` | thời gian evidence do agent ghi |
| `recorded_at TEXT NOT NULL` | thời gian journal commit theo UTC |
| `priority TEXT NOT NULL` | `BULK`, `OPERATIONAL`, `SECURITY`, `UNCLASSIFIED` |
| `payload TEXT NOT NULL` | canonical JSON của NormalizedEvent |
| `payload_bytes INTEGER NOT NULL` | kích thước UTF-8 dùng cho logical quota |
| `previous_hash TEXT NOT NULL` | hash record trước trong cùng priority chain |
| `record_hash TEXT NOT NULL UNIQUE` | SHA-256 của chain input canonical |
| `delivery_state TEXT NOT NULL` | `PENDING`, `ACKED`, `QUARANTINED` |
| `acknowledged_at TEXT NULL` | UTC server acknowledgement |
| `quarantine_reason TEXT NULL` | bounded reason, không chứa response body |

Constraints kiểm tra priority/state, non-negative bytes, acknowledgement/quarantine invariants và
UTC-aware timestamp format tại application boundary. Payload, event identity, timestamps, priority
và chain fields bất biến sau insert. Chỉ delivery fields được update.

Indexes:

- `(delivery_state, sequence)` cho oldest-first delivery;
- `(event_type, recorded_at)` cho status/retention;
- `(priority, recorded_at)` cho pressure pruning.
- unique `(priority, chain_sequence)` giữ từng priority chain liên tục.

### `coverage_gaps`

Bounded tối đa 1.000 hàng:

- `id`, `started_at`, `ended_at`, `category`, `reason`, `dropped_event_count`.

Category ban đầu: `STORAGE_LIMIT`, `STORAGE_WRITE_FAILURE`, `CLOCK_REGRESSION`,
`LEGACY_MIGRATION_FAILURE`. Raw payload, exception text và secret không được lưu. Một khoảng đang mở
được gộp counter thay vì tạo vô hạn hàng.

Nếu chính SQLite không thể ghi coverage gap, agent ghi fallback sidecar `coverage-gap.json` bằng
atomic replace + file/directory fsync, mode `0600`. File chỉ có bounded timestamps/category/count,
không có payload. Lần mở store thành công kế tiếp import gap vào SQLite rồi xóa sidecar. Vì vậy lỗi
disk/database không bị báo thành một chu kỳ “yên lặng”. Sidecar cũng không thể đảm bảo ghi được khi
toàn filesystem hết chỗ; trường hợp đó vẫn phải phát bounded stderr/journal log và trạng thái cycle
degraded.

### Metadata

`local_store_metadata` giữ `policy_version`, trạng thái legacy migration, và cho mỗi priority:
`last_chain_sequence`, `last_chain_hash`, `pruned_through_chain_sequence`,
`pruned_through_hash`. Metadata mutable không nằm trong hash chain.

## 7. Hash chain

Canonical payload dùng UTF-8 JSON với key sort, compact separator và UTC timestamp chuẩn hóa. Mỗi
priority có chain riêng. Cách này quan trọng vì retention của `BULK`, `OPERATIONAL` và `SECURITY`
khác nhau; xóa một prefix của chain BULK không được làm đứt chain SECURITY. Chain input gồm:

```text
priority | chain_sequence | event_id | recorded_at | payload_bytes | previous_hash | canonical_payload
```

`record_hash = SHA256(chain_input)`.

Insert batch được serialize dưới một async lock và một `BEGIN IMMEDIATE` transaction để hai writer
không nhận cùng previous hash. Verification đọc theo `(priority, chain_sequence)` và kiểm tra UUID
uniqueness, byte size, previous hash và computed hash.

Retention chỉ được xóa một **contiguous eligible prefix** của từng priority chain. Trước khi xóa,
transaction lưu `pruned_through_chain_sequence` và `pruned_through_hash`; record còn lại đầu tiên phải
trỏ về anchor hash này. Nếu một Event cũ còn `PENDING`/`QUARANTINED`, prefix dừng tại đó và không nhảy
qua để tạo lỗ chain. `UNCLASSIFIED` chain không được prune. Vì vậy verification sau retention vẫn có
điểm bắt đầu rõ ràng mà không cần giữ payload đã hết hạn.

Giới hạn bảo mật: hash chain local chỉ phát hiện corruption/tampering khi chain hoặc checkpoint tin
cậy còn tồn tại. Root attacker có thể rewrite toàn bộ chain. Selective Sync sau này sẽ gửi signed
checkpoint `(device_id, sequence, record_hash)` lên server để việc rewrite lịch sử trở nên phát hiện
được. Milestone này không quảng cáo tamper-proof storage.

## 8. Priority và retention local v1

Age dùng `recorded_at`, không dùng clock field bên trong payload.

| Priority | Event types | Minimum retention |
|---|---|---:|
| `BULK` | resource usage và listener/connection observations | 24 giờ |
| `OPERATIONAL` | `system.status` | 7 ngày |
| `SECURITY` | process/network opened/closed/started/exited | 30 ngày |
| `UNCLASSIFIED` | unknown/future event type | không tự động xóa |

Cutoff inclusive. Chỉ Event `ACKED` mới được automatic/manual retention prune. `PENDING`,
`QUARANTINED`, `UNCLASSIFIED` và future pinned evidence không được tự động xóa.

Vì endpoint clock có thể lùi, `recorded_at` mới là `max(current_utc, last_recorded_at)` và một
`CLOCK_REGRESSION` gap/warning được ghi khi phát hiện. Cách này ưu tiên giữ evidence lâu hơn thay vì
xóa sớm sai. Nó không biến local clock thành nguồn thời gian đáng tin; server vẫn dùng `ingested_at`
cho server retention.

Default logical payload quota là 256 MiB, configurable bằng
`AEGISX_LOCAL_TELEMETRY_MAX_BYTES`, bounded từ 64 MiB đến 10 GiB. Quota tính tổng `payload_bytes`,
không hứa file SQLite luôn đúng bằng con số đó vì WAL/page reuse.

Khi append vượt quota, store được phép prune contiguous eligible prefix của chain theo thứ tự:
`BULK`, `OPERATIONAL`, rồi `SECURITY`. Nó không được xóa Event còn retention chỉ để nhận Event mới,
và không được nhảy qua một pending/quarantined row. Nếu vẫn thiếu chỗ, batch mới không được coi là đã
lưu; agent mở/cập nhật coverage gap, log bounded error và không enqueue batch đó. Không có silent
eviction.

## 9. Delivery và crash semantics

Append journal + tạo `PENDING` diễn ra trong một transaction. Nếu transaction fail, không Event nào
trong batch được coi là queued.

Server `accepted` và `duplicate` đều là acknowledgement hợp lệ. Store update Event thành `ACKED` và
loại nó khỏi delivery view trong cùng transaction. HTTP 400/422 single-event isolation chuyển Event
sang `QUARANTINED`; lý do chỉ là category như `http_422`.

Transport, timeout, 429 và 5xx giữ `PENDING`. 401/403 giữ evidence và propagate lỗi như hiện tại.
Delivery luôn theo sequence tăng dần. Server UUID deduplication tiếp tục bảo vệ resend.

Cancellation đợi SQLite worker operation đang chạy kết thúc trước khi release lock. Mọi SQLite call
tiếp tục chạy ngoài async event loop.

## 10. Upgrade từ outbox hiện tại

Upgrade chạy trong chính `outbox.sqlite3`:

1. kiểm tra file là regular file thuộc user hiện tại, không phải symlink;
2. chạy `PRAGMA quick_check`;
3. bắt đầu exclusive schema transaction;
4. tạo schema version 2;
5. import `pending_events` theo sequence thành journal `PENDING`;
6. import `quarantined_events` thành journal `QUARANTINED`;
7. verify số UUID distinct và payload parse được;
8. drop legacy pending/quarantine tables trong cùng transaction sau khi import đã verify;
9. chỉ sau verification mới chuyển `user_version` sang 2 và commit.

Legacy payload được chain theo thứ tự pending trước, quarantine sau; `recorded_at` migration time vì
schema cũ không có enqueue time. Original Event timestamp vẫn ở payload. ACKED historical Events đã
bị xóa khỏi schema cũ nên không thể khôi phục và không được giả lập.

Failure rollback toàn schema transaction và agent tiếp tục dùng legacy outbox ở chế độ delivery-only
nếu file còn hợp lệ. Nó ghi coverage warning ra bounded log; không rename, truncate hoặc reset file.

## 11. Filesystem và corruption safety

- state directory mode `0700`, database mode `0600`;
- refuse symlink và non-regular database target;
- SQLite WAL, foreign keys on, busy timeout bounded, `synchronous=FULL` cho journal evidence;
- startup `quick_check`; failure không auto-delete database;
- schema version mới hơn code phải fail closed với hướng dẫn upgrade;
- errors/logs không chứa token, payload, command line hoặc raw SQL.

Milestone này không encrypt SQLite. File permissions bảo vệ user khác nhưng không bảo vệ root hoặc
malware chạy cùng UID. Encryption/key storage cần thiết kế riêng với optional TPM/OS keyring; không
hard-code key hoặc lưu key cạnh database rồi gọi đó là bảo mật.

## 12. CLI

Các command local không cần PostgreSQL, Docker hay Podman:

```text
aegisx local-data-status
aegisx local-verify
aegisx local-prune --dry-run
aegisx local-prune --apply --yes
```

`local-data-status` báo schema/policy version, logical bytes, file bytes, số Event theo type/priority/
delivery state, oldest/newest và coverage gaps. `local-verify` kiểm tra SQLite quick-check và toàn hash
chain, trả non-zero tại sequence đầu tiên bị lỗi nhưng không in payload.

Dry-run báo cutoff và deletable ACKED rows. Apply bắt buộc `--yes`, xóa batch tối đa 1.000 rows mỗi
transaction, không chạy `VACUUM FULL`, không đụng identity/credentials/baseline. CLI mặc định dùng
`AEGISX_AGENT_STATE_DIR` hoặc `$HOME/.local/state/aegisx`.

## 13. Chuẩn bị cho blocking tương lai

Foundation này chỉ chuẩn bị evidence, không ra quyết định và không thực thi action:

- Event UUID/sequence/hash ổn định để Decision trỏ về evidence chính xác;
- delivery state tách khỏi evidence content;
- future Detection có thể pin pre/post-event window trước retention;
- coverage gap ngăn policy hiểu nhầm “không thấy Event” thành “máy an toàn”;
- future ResponseReceipt sẽ là Event bất biến priority `SECURITY`, nhưng schema/action chưa được thêm;
- future privileged executor không được truy cập trực tiếp để sửa/xóa journal.

Trước auto-block còn bắt buộc có local deterministic Detection, signed versioned Policy, ambiguity
fail-closed, allowlist, approval levels, circuit breaker, TTL, rollback và privilege separation.

## 14. Tests bắt buộc

### Unit/SQLite tests

- append batch tạo contiguous sequence/hash và `PENDING` atomically;
- duplicate UUID idempotent khi payload giống hệt, error khi cùng UUID khác payload;
- accepted/duplicate acknowledgement giữ journal row và bỏ delivery view;
- quarantine giữ evidence/reason nhưng không retry;
- transient/auth failures không đổi evidence;
- restart giữ oldest-first delivery;
- cancellation không cho concurrent connection use;
- legacy pending/quarantine migration thành công và idempotent;
- malformed legacy payload/schema migration failure rollback nguyên file;
- symlink, permission và future schema version bị từ chối;
- quick-check/hash corruption được phát hiện không auto-reset;
- exact retention boundaries theo `recorded_at` và prune chỉ contiguous prefix mỗi priority chain;
- prune anchor giữ chain verifiable và pending/quarantined row chặn prefix deletion;
- unknown, pending, quarantined và not-yet-expired rows không bị prune;
- logical quota prune đúng priority hoặc tạo coverage gap, không silent drop;
- status/verify output không lộ payload/token/command line.

### Runner tests

- journal transaction hoàn tất trước network call;
- successful delivery leaves local `ACKED` evidence;
- offline cycle leaves local `PENDING` evidence;
- invalid server event leaves local `QUARANTINED` evidence;
- local write failure prevents send and reports deferred/degraded coverage;
- clock rollback không làm `recorded_at` lùi hoặc prune evidence sớm;
- current collection/delivery counts and server UUID idempotency remain compatible.

### CLI/integration tests

- local commands run without Compose/PostgreSQL;
- apply refuses without `--yes`;
- real two-cycle agent smoke creates verifiable local chain;
- server ingestion/Detection/Correlation/Incident behavior remains unchanged;
- API, agent, launcher, PostgreSQL, Ruff, strict mypy, Compose and whitespace checks pass.

## 15. Demo để người dùng test trước khi selective sync

Sau implementation:

```bash
aegisx run
# chờ ít nhất hai collection cycles rồi thoát bằng q
aegisx local-data-status
aegisx local-verify
aegisx local-prune --dry-run
```

Kết quả cần thấy: Event local tồn tại dù server đã ACK; pending thường bằng 0 khi online; hash chain
valid; dry-run không xóa gì khi Event còn trong retention. PostgreSQL vẫn nhận cùng Event như trước.

## 16. Không làm trong milestone này

- selective sync hoặc giảm thêm Event gửi server;
- realtime eBPF/kernel collector;
- local Detection/Correlation/Incident;
- Decision/Policy implementation;
- process kill, network block, endpoint isolation hoặc privileged helper;
- encryption, TPM, secure boot hoặc remote attestation;
- signed server checkpoint;
- scheduled prune daemon;
- web/desktop UI, AI hoặc notifications.

## 17. Known limitations

- Foundation đầu tiên tạm thời tăng local disk usage vì ACKED Event được giữ thay vì xóa ngay.
- Polling vẫn bỏ lỡ process/socket sống ngắn hơn collection interval.
- Local hash chain chưa anchor lên server nên root rewrite toàn chain vẫn có thể che giấu thay đổi.
- Legacy ACKED Events không còn trong old outbox nên không thể khôi phục.
- Logical quota không đồng nghĩa file SQLite co lại ngay; page/WAL được reuse theo SQLite behavior.
- Quarantined và unknown data không auto-prune có thể tạo storage pressure; operator phải review.
- Server vẫn lưu mọi Event được agent phát ra cho tới selective-sync milestone.
