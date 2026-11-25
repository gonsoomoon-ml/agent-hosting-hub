# 카탈로그

허브에서 쓸 수 있는 도구와 에이전트의 목록입니다. AWS Agent Registry(`<prefix>-registry`)에 레코드로 둡니다. 승인은 수동이라서 플랫폼팀이나 호스팅 심사가 승인한 레코드만 검색에 나옵니다. 공유 도구 레코드 `parts-tools`는 `make seed`가 넣고 승인합니다.

## 개념도에서의 위치

[개념도](../../docs/hosting-hub-concept.png)의 흐름 1의 "카탈로그: 승인된 것만 검색" 상자입니다. 개발팀은 ① "에이전트와 도구 검색"에서 여기를 찾고, ② "에이전트 호스팅 신청"에서 레코드를 만들어 승인을 요청합니다. 심사가 끝나면 ⑥의 6b "승인 표시"로 레코드가 승인됩니다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | Registry(수동 승인, IAM 인증). 내보내는 값은 `registry_id`, `registry_arn`. |
| `application_form.py` | 에이전트 신청서(`agent.json`)를 검사합니다. 이름 규칙과 카탈로그의 도구를 보고, 이름에서 만드는 정책 이름이 한도(48자)에 맞는지 봅니다. 제출할 때와 심사의 Read 단계에서 돕니다. |
| `catalog_records.py` | 레코드를 만들거나 고치고(`put_record`), 승인을 요청하고(`submit`), 상태를 바꾸고(`set_status`), 검색하고(`search`), 목록을 읽습니다(`records`). |
| `seed_catalog.py` | 공유 도구 레코드 `parts-tools`를 만들고 승인합니다(`make seed`). `--remove`는 그 레코드를 지웁니다(`make destroy`가 Terraform보다 먼저 부릅니다. 레코드가 남은 Registry는 지워지지 않습니다). |
| `search_catalog.py` | 카탈로그를 검색해 승인된 레코드의 이름, 종류, 설명, 도구의 입력 필드를 출력합니다(`demo_scenes/search`). 개발자 역할이 쓰는 읽기 호출만 씁니다. 2026-11-23에 개발팀 역할로 AWS에서 돌렸습니다(`parts-tools`의 도구 입력 필드까지 출력했습니다). |
