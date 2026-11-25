# 샘플 사내 도구

허브의 도구 게이트웨이 뒤에서 동작하는 샘플 도구 모음입니다. 검사, 부품, 배포 검토를 맡는 회사의 자체 시스템을 흉내 냅니다. 모든 데이터는 합성이고, 실제 회사, 제품, 사람, 계정 정보는 없습니다.

## 개념도에서의 위치

[개념도](../../docs/hosting-hub-concept.png)의 흐름 2의 "사내 도구" 상자입니다. ⑨ "허용된 호출만 전달" 단계에서 게이트웨이가 정책을 통과한 호출만 이 Lambda로 넘깁니다.

## 도구 목록이 쓰이는 곳

도구의 목록과 스키마는 `tool_schema.py`의 `TARGETS` 한 곳에 있고, 허브의 여러 곳이 이 목록을 씁니다.

```
platform_team/sample_tools/tool_schema.py
  TARGETS = { Quality: [get_inspection_data],
              Parts:   [get_part_spec, get_test_result],
              Release: [file_review_request] }
  SHARED_READ = ["Parts___get_part_spec"]
        │
        ├─▶ make package → build/tool_schemas.json, build/shared_read.json
        │       │
        │       ├─▶ Terraform: 도구 게이트웨이의 target 셋 (Quality, Parts, Release), 스키마 포함
        │       └─▶ Terraform: 개발팀 역할의 permit shared_tool_read (SHARED_READ의 도구 하나)
        │
        ├─▶ make seed: 카탈로그의 MCP 레코드 parts-tools
        │
        └─▶ publish.sh: 신청서의 tools가 이 목록에 있는지 검사
```

## 호출 하나가 지나는 길

```
에이전트: call_tool("Quality___get_inspection_data", {"case_id": "Q-1001"})
  │
  ▼
도구 게이트웨이 <prefix>-tools
  │  permit 확인 → target "Quality"
  │  Lambda를 부릅니다:  event = {"case_id": "Q-1001"}   (인자만)
  │                      도구 이름은 context.client_context.custom["bedrockAgentCoreToolName"]
  ▼
Lambda <prefix>-tools  (target 셋이 같은 Lambda)
  │  tool_handler.handler → TOOLS["Quality___get_inspection_data"]
  ▼
{"case_id": "Q-1001", "part_id": "P-100", "result": "PASS", "inspector_id": "EMP-204817", "synthetic": true}
```

- 모든 답에 `"synthetic": true`가 붙습니다. 오류도 예외가 아니라 `{"error": ..., "synthetic": true}`로 돌려줍니다.
- 아무것도 저장하지 않습니다. 검토 요청 번호(`RR-<8자>`)는 `change_id`와 `summary`의 해시라서, 같은 입력이면 같은 번호입니다.

## 데이터와 데모에서의 쓰임

| 데이터 | 값 | 쓰이는 곳 |
|---|---|---|
| `Q-1001` | `PASS`, 검사원 `EMP-204817` | 커스텀 가드레일이 답의 사번을 `{employee_id}`로 가립니다 |
| `Q-1002` | `PENDING`, 바뀌지 않습니다 | `quality_agent`의 `v2-loop`이 반복하는 사고 |
| `P-100` | `M4 x 12 mm, steel` | 심사의 시험 호출, `spec_assistant`의 질문 |
| `file_review_request` | `RR-<8자>` | `release_review`가 위반을 찾으면 올리는 검토 요청 |

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | Lambda `<prefix>-tools`, 그 역할 `<prefix>-tools-lambda-role`, 로그 그룹. 코드는 `make package`가 만드는 허브의 코드 패키지 `build/platform_team.zip`입니다. 내보내는 값은 `lambda_arn`. |
| `tool_handler.py` | Lambda 진입점. 도구 이름(`<Target>___<tool>`)을 읽어 알맞은 도구를 실행합니다. 표준 라이브러리만 쓰고 상태를 저장하지 않습니다. |
| `tool_data.py` | 합성 검사 건, 부품, 시험 결과. |
| `tool_schema.py` | 게이트웨이에 등록할 도구 스키마(`TARGETS`)와 승인된 공유 읽기 도구(`SHARED_READ`). |
