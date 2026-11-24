# 구조와 코드

[README](../README.md)로 돌아가기

허브의 그림 둘, 폴더마다 들어 있는 것, 흐름이 지나가는 코드를 적는다. 폴더의 트리는 [README](../README.md#무엇이-들어-있나)에 있다.

## 그림 둘

![개념도: 흐름 1(호스팅)과 흐름 2(운영)](hosting-hub-concept.png)

개념도(`docs/hosting-hub-concept.png`)는 두 흐름을 상자와 번호 붙은 화살표로 그린 것이다. 흐름 1(호스팅)은 ①부터 ⑥까지이고(④-1은 심사가 실패했을 때의 길이다), 흐름 2(운영)는 ⑦부터 ⑫까지다(⑥은 6a와 6b, ⑦은 7a와 7b로 나뉘어 그려져 있다). 각 기능의 README는 "개념도에서의 위치"에서 자기 상자와 번호를 가리킨다.

![구성도: 같은 두 흐름을 AWS 서비스 이름으로 그린 그림](hosting-hub-system.png)

구성도(`docs/hosting-hub-system.png`)는 같은 자리에 AWS 서비스의 이름을 넣은 것이다. 예를 들어 ⑤는 심사의 배포 단계가 부르는 `CreateAgentRuntime`이다. 두 그림은 한국어로만 있고, 그림의 원본 파일은 이 저장소에 없다. 허브 화면(`platform_team/hub_ui/static/`)에는 흐름마다 하나씩 나눈 더 작은 그림 둘이 따로 들어 있다.

## 폴더마다 들어 있는 것

| 폴더 | 누가 쓰나 | 내용 |
|---|---|---|
| `platform_team/` | 플랫폼팀 | 허브의 기반 자원과 운영 명령. 기능마다 폴더 하나이고, AWS에 기반 자원을 두는 기능은 그 안에 Terraform 모듈이 있다. [게이트웨이 둘](../platform_team/agent_gateway/README.md)([도구 쪽](../platform_team/tool_gateway/README.md)), [전사 정책](../platform_team/company_policy/README.md), [카탈로그](../platform_team/agent_catalog/README.md), [호스팅 심사](../platform_team/hosting_review/README.md), [샘플 사내 도구](../platform_team/sample_tools/README.md), [모니터링](../platform_team/agent_monitoring/README.md), [개발팀의 권한](../platform_team/dev_access/README.md), [커스텀 가드레일](../platform_team/custom_guardrail/README.md), [에이전트 멈추기와 재개](../platform_team/agent_stop/README.md)(Terraform 없음), [허브 화면](../platform_team/hub_ui/README.md)(샘플, 이 PC에서만, Terraform 없음) |
| `dev_team/` | 개발팀 | [에이전트 템플릿](../dev_team/agent_template/README.md)과 올리는 명령(`publish.sh`), 예시 에이전트 둘: [release_review](../dev_team/release_review/README.md)(LangGraph), [quality_agent](../dev_team/quality_agent/README.md)(Strands). `preloaded_agents/`에는 미리 올려 둔 에이전트 둘이 있다(플랫폼팀이 `make preload`로 올린다): [docs_adk](../dev_team/preloaded_agents/docs_adk/README.md)(Google ADK), [spec_assistant](../dev_team/preloaded_agents/spec_assistant/README.md)(코드가 없는 managed harness). [시작하기](getting-started.md#미리-올려-둔-에이전트-둘)의 "미리 올려 둔 에이전트 둘" |
| `e2e_checks/` | 누구나 | 실제 AWS에서 돌리는 확인 스크립트. `e2e_hosting.py`(흐름 1의 처음부터 끝까지), `e2e_operations.py`(흐름 2의 처음부터 끝까지), `check_platform.py`(허브의 기반 자원), `check_cleanup.py`(지운 뒤 남은 것). `spikes/`는 제품의 일부가 아니라 만들면서 가정을 확인한 스크립트다([확인 테스트](../e2e_checks/spikes/README.md)) |
| `tests/` | 누구나 | 단위 테스트(`make test`). AWS를 부르지 않는다. |

## 코드 따라 읽기

흐름 1(호스팅)의 첫 두 단계가 코드의 어디를 지나가는지 적는다. 번호는 위 [개념도](hosting-hub-concept.png)의 번호다.

| 단계 | 일어나는 일 | 들어가는 곳 |
|---|---|---|
| ① 에이전트와 도구 검색 | 개발자가 카탈로그에서 승인된 레코드를 찾는다. 승인되지 않은 레코드는 검색에 나오지 않는다. | `demo_scenes/search` → `platform_team/agent_catalog/search_catalog.py` → `platform_team/agent_catalog/catalog_records.py`의 `search_records()` |
| ② 에이전트 호스팅 신청 | `publish.sh <에이전트 폴더>`가 네 가지를 차례로 한다. 신청서(`agent.json`)를 검사한다. 폴더 맨 위의 `.py` 파일과 `requirements.txt`를 zip으로 묶어 제출 버킷(S3 bucket)에 올린다. 신청서를 카탈로그의 레코드로 쓴다. 승인을 요청한다. 레코드가 `PENDING_APPROVAL`이 되면 그 이벤트가 호스팅 심사를 시작한다. | `dev_team/agent_template/publish.sh` → `platform_team/agent_catalog/publish_agent.py`의 `publish()` |

②에서 `publish()`가 차례로 부르는 것은 이렇다.

- 검사: `platform_team/agent_catalog/application_form.py`의 `validate()`
- 묶기: `platform_team/agent_catalog/publish_agent.py`의 `bundle()`. 변형을 주면 `variants/<변형>/`의 파일이 폴더의 파일을 대신한다.
- 레코드 쓰기와 승인 요청: `platform_team/agent_catalog/catalog_records.py`의 `put_record()`와 `submit()`. 승인 요청은 레코드를 쓴 뒤의 상태가 `DRAFT`일 때만 한다. 바뀐 것이 없는 재신청처럼 상태가 그대로이면 다시 요청하지 않는다.
- 심사의 시작: `platform_team/hosting_review/terraform/main.tf`의 `aws_cloudwatch_event_rule.on_submit`
