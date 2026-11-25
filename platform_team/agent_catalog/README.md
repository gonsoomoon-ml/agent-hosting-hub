# 카탈로그

허브에서 쓸 수 있는 도구와 에이전트의 목록입니다. AWS Agent Registry(`<prefix>-registry`)에 레코드로 둡니다. 승인은 수동이라서 플랫폼팀이나 호스팅 심사가 승인한 레코드만 검색에 나옵니다. 공유 도구 레코드 `parts-tools`는 `make seed`가 넣고 승인합니다.

## 개념도에서의 위치

[개념도](../../docs/hosting-hub-concept.png)의 흐름 1의 "카탈로그: 승인된 것만 검색" 상자입니다. 개발팀은 ① "에이전트와 도구 검색"에서 여기를 찾고, ② "에이전트 호스팅 신청"에서 레코드를 만들어 승인을 요청합니다. 심사가 끝나면 ⑥의 6b "승인 표시"로 레코드가 승인됩니다.

## 레코드의 상태

```
publish.sh → put_record()
  │   레코드를 만들거나 고칩니다. 새 레코드와 고친 레코드는 DRAFT입니다
  ▼
DRAFT
  │   submit()   (publish.sh가 이어서 부릅니다)
  ▼
PENDING_APPROVAL
  │   EventBridge rule <prefix>-on-submit → 호스팅 심사 시작
  │
  ├─ 심사 통과 → Approve Lambda가 APPROVED로 바꿉니다   "passed the hosting review"
  │                └─ 이제 검색에 나옵니다
  │
  └─ 심사 실패 → 플랫폼팀 reject.sh가 REJECTED로 바꿉니다  "<사유>"
                   └─ 팀은 레코드에서 사유를 읽고 고쳐서 다시 제출합니다
```

공유 도구 레코드 `parts-tools`는 심사를 거치지 않고, `make seed`가 만들어 바로 승인합니다. 내용이 같은 레코드를 다시 쓰면 Registry가 고친 것으로 보지 않아 상태가 그대로이고, 그때 `publish.sh`는 승인을 다시 요청하지 않습니다.

## 레코드 안에 든 것

```
AGENT 레코드 "quality_agent"
  ├─ name, description, recordType = AGENT
  └─ custom descriptor (JSON)
       ├─ agent.json의 칸들:  name, team, framework, description, tools
       ├─ code_key:           submissions/appliance/quality_agent/agent.zip
       └─ code_version:       S3 object version   ← 심사의 Scan과 Deploy가 꼭 이 version을 읽습니다

MCP 레코드 "parts-tools"
  └─ custom descriptor: target 이름과 도구 목록 (입력 필드 포함)
```

## 개발팀이 쓰는 법

```
① 검색   demo_scenes/search "<찾는 말>"
           → 승인된 레코드의 이름, 종류, 설명, 도구의 입력 필드
② 신청   agent.json의 tools에 찾은 도구를 <Target>___<tool>로 적고 publish.sh
           → 신청서 검사(application_form.validate)를 통과해야 레코드가 만들어집니다
```

신청서 검사가 "카탈로그의 도구"로 보는 것은 코드의 도구 목록(`platform_team/sample_tools`의 `TARGETS`)입니다. `parts-tools` 레코드도 같은 목록으로 만듭니다. 신청서의 규칙은 [에이전트 템플릿](../../dev_team/agent_template/README.md)에 있습니다.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | Registry(수동 승인, IAM 인증). 내보내는 값은 `registry_id`, `registry_arn`. |
| `application_form.py` | 에이전트 신청서(`agent.json`)를 검사합니다. 이름 규칙과 카탈로그의 도구를 보고, 이름에서 만드는 정책 이름이 한도(48자)에 맞는지 봅니다. 제출할 때와 심사의 Read 단계에서 돕니다. |
| `catalog_records.py` | 레코드를 만들거나 고치고(`put_record`), 승인을 요청하고(`submit`), 상태를 바꾸고(`set_status`), 검색하고(`search`), 목록을 읽습니다(`records`). |
| `seed_catalog.py` | 공유 도구 레코드 `parts-tools`를 만들고 승인합니다(`make seed`). `--remove`는 그 레코드를 지웁니다. 레코드가 남은 Registry는 지워지지 않으므로 `make destroy`가 Terraform보다 먼저 부릅니다. |
| `search_catalog.py` | 카탈로그를 검색해 승인된 레코드의 이름, 종류, 설명, 도구의 입력 필드를 출력합니다(`demo_scenes/search`). 개발팀 역할이 쓰는 읽기 호출만 쓰고, 2026-11-23에 그 역할로 AWS에서 돌렸습니다. |
