# 카탈로그

허브에서 쓸 수 있는 도구와 에이전트의 목록이다. AWS Agent Registry(`<prefix>-registry`)에 record로 둔다. 승인은 수동이라서 플랫폼팀이나 호스팅 심사가 승인한 record만 검색에 나온다. 공유 도구 record `parts-tools`는 `make seed`가 넣고 승인한다.

## 개념도에서의 위치

"카탈로그: 승인된 것만 검색" 상자다. 개발팀은 ① "에이전트와 도구 검색"에서 여기를 찾고, ② "에이전트 호스팅 신청"에서 record를 만들어 승인을 요청한다. 심사가 끝나면 ⑥ "승인 표시"로 record가 승인된다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | Registry(수동 승인, IAM 인증). 내보내는 값은 `registry_id`, `registry_arn`. |
| `application_form.py` | 에이전트 신청서(`agent.json`)를 검사한다. 이름 규칙과 카탈로그의 도구를 보고, 이름에서 만드는 정책 이름이 한도(48자)에 맞는지 본다. 제출할 때와 심사의 Read 단계에서 돈다. |
| `catalog_records.py` | record를 만들거나 고치고(`put_record`), 승인을 요청하고(`submit`), 상태를 바꾸고(`set_status`), 검색하고(`search`), 목록을 읽는다(`records`). |
| `seed_catalog.py` | 공유 도구 record `parts-tools`를 만들고 승인한다(`make seed`). `--remove`는 그 record를 지운다(`make destroy`가 Terraform보다 먼저 부른다. record가 남은 Registry는 지워지지 않는다). |
| `search_catalog.py` | 카탈로그를 검색해 승인된 record의 이름, 종류, 설명, 도구의 입력 필드를 찍는다(`demo_scenes/search`). 개발자 역할이 쓰는 읽기 호출만 쓴다. 2026-11-23에 개발팀 역할로 AWS에서 돌렸다(`parts-tools`의 도구 입력 필드까지 찍었다). |
