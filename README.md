# AI 에이전트 호스팅 허브

Amazon Bedrock AgentCore 위에서 여러 개발팀의 AI 에이전트를 한곳에 올리고 관리하는 허브를 만든다.
플랫폼팀은 허브(게이트웨이, 정책, 레지스트리)를 만들고, 개발팀은 에이전트를 만들어 허브에 올린다.
정책은 Cedar로 쓰고, 어떤 에이전트가 어떤 도구를 쓸 수 있는지 허브가 정한다.

> 만드는 중입니다. 지금 들어 있는 것은 흐름 1(호스팅: 신청, 심사, 승인, 반려와 재신청)입니다. 흐름 2(운영)는 다음 계획에서 더합니다.

## 무엇이 들어 있나

| 폴더 | 누가 쓰나 | 내용 |
|---|---|---|
| `platform_team/` | 플랫폼팀 | 허브의 틀과 운영 명령. 기능마다 폴더 하나이고, AWS에 틀을 두는 기능은 그 안에 Terraform 모듈이 있다. [게이트웨이 둘](platform_team/agent_gateway/README.md)([도구 쪽](platform_team/tool_gateway/README.md)), [전사 정책](platform_team/company_policy/README.md), [카탈로그](platform_team/agent_catalog/README.md), [호스팅 심사](platform_team/hosting_review/README.md), [샘플 사내 도구](platform_team/sample_tools/README.md), [모니터링](platform_team/agent_monitoring/README.md), [개발팀의 권한](platform_team/dev_access/README.md), [커스텀 가드레일](platform_team/custom_guardrail/README.md), [에이전트 멈추기와 재개](platform_team/agent_stop/README.md)(Terraform 없음) |
| `dev_team/` | 개발팀 | [에이전트 템플릿](dev_team/agent_template/README.md)과 올리는 명령(`publish.sh`), 예시 에이전트 둘: [release_review](dev_team/release_review/README.md)(LangGraph), [quality_agent](dev_team/quality_agent/README.md)(Strands) |
| `e2e_checks/` | 누구나 | 실제 AWS에서 돌리는 확인 스크립트. `e2e_hosting.py`(흐름 1의 끝에서 끝까지), `check_platform.py`(허브의 틀), `check_cleanup.py`(지운 뒤 남은 것). `spikes/`는 제품의 일부가 아니라 만들면서 가정을 확인한 스크립트다([확인 시험](e2e_checks/spikes/README.md)) |
| `tests/` | 누구나 | 단위 시험(`make test`). AWS를 부르지 않는다. |

## 사전 요건

- Terraform 1.9 이상, Python 3.12 이상과 [uv](https://docs.astral.sh/uv/), bash
- AWS 자격 증명. 허브는 IAM 역할, 정책 엔진, 게이트웨이, Lambda, CodeBuild, Step Functions, S3 bucket 등을 만든다. 이 문서의 시간은 관리자 권한의 자격 증명으로 잰 것이다.
- 리전 `us-west-2`. 셸의 기본 리전이 다르면 `AWS_REGION=us-west-2`(도구에 따라 `AWS_DEFAULT_REGION`도)를 준다. 리전, 접두어, 모델은 `.env`로도 정할 수 있다(아래 "`.env`").
- Amazon Bedrock 모델 사용 권한. 에이전트가 부르는 모델은 `MODEL_ID`(기본값은 추론 프로파일 `us.anthropic.claude-haiku-4-5-20251001-v1:0`)다.

### `.env`

`.env.example`을 `.env`로 복사하면 허브의 세 값, 리전(`AWS_REGION`), 접두어(`DEMO_PREFIX`), 모델(`MODEL_ID`)을 거기서 읽는다. `make`, `publish.sh`, `reject.sh`, `rollout.sh`, `guardrail.sh`, `stop.sh`, `resume.sh`, `e2e_checks/`의 스크립트 셋(`e2e_hosting.py`, `check_platform.py`, `check_cleanup.py`)이 모두 같은 규칙을 따른다.

- `.env`에서 읽는 것은 이 세 줄뿐이다. 다른 줄은 읽지도 내보내지도 않는다. 그래서 `.env`에 자격 증명을 적어 두어도 명령이 쓰는 자격 증명은 바뀌지 않는다.
- 한 줄에 `이름=값`으로 쓴다. 따옴표, `export`, `=` 앞뒤의 빈칸은 쓰지 않는다. `make`와 셸은 따옴표를 다르게 읽기 때문이다. 같은 이름이 두 번 나오면 마지막 줄을 쓴다. 값이 빈 줄(`DEMO_PREFIX=`)은 없는 줄과 같아서, 그 이름은 셸의 값이나 기본값을 쓴다. `make`, `publish.sh`, `reject.sh`, `rollout.sh`, `guardrail.sh`, `stop.sh`, `resume.sh`, `e2e_hosting.py`, `check_platform.py`, `check_cleanup.py`가 같은 규칙을 따른다.
- 어느 값을 쓰나: `make`의 명령줄에 준 값(`make deploy DEMO_PREFIX=demo`)이 가장 앞서고, 그다음이 `.env`, 그다음이 셸의 환경 변수, 마지막이 기본값(`us-west-2`, `hub`, 아래의 모델)이다. `make`가 부르는 명령(`make publish`, `make e2e`)은 `make`가 정한 값을 그대로 쓰고 `.env`를 다시 읽지 않는다(그 표시가 `HUB_ENV_LOADED=1`이다). `publish.sh`, `reject.sh`, `rollout.sh`, `guardrail.sh`, `stop.sh`, `resume.sh`, `e2e_hosting.py`를 직접 부르면 같은 규칙으로 `.env`를 읽는다. `e2e_hosting.py`가 부르는 두 명령은 그 스크립트가 정한 값을 쓴다.
- 접두어는 소문자로 시작하는 2~10자의 소문자와 숫자다(`hub`, `demo2`). 정책 엔진, Runtime, 게이트웨이, bucket의 이름이 접두어로 시작하는데, 그 이름들의 규칙을 모두 지키는 모양이 이것이다. 다른 모양이면 Terraform(`make deploy`)과 Python 명령이 아무것도 만들기 전에 거부한다.

`.env`를 읽는 규칙과 `Settings`의 접두어 거절은 단위 시험(`tests/test_hub_env.py`)이 확인한다. Terraform의 거절은 Terraform의 `validation`이 하는 것이고, 2026-11-22에 `terraform plan -var prefix=…`로 `my-hub`, `Hub`, `hub_1`이 `Invalid value for variable`로 거절되는 것을 봤다. AWS에서는 `.env` 없이 셸의 `AWS_REGION`과 기본값으로만 돌렸으므로, `.env`를 읽는 길은 AWS에서 확인하지 않았다.

## 다섯 명령

시간은 2026-11-22의 실행(`us-west-2`, 접두어 `hub`)에서 잰 것이다. "고친 뒤의 실행"은 같은 날 최종 검토의 지적을 고친 코드로 `make deploy`, `make seed`, `make e2e`, `make destroy`를 한 번씩 돌린 것이다. `make deploy`와 `make destroy`는 `AUTO_APPROVE=1`로 돌렸으므로 `yes`를 묻는 대화는 확인하지 않았다.

열 "CLI로 배포하던 때"의 시간은 심사의 배포 단계가 AgentCore CLI(`agentcore deploy`, CDK와 CloudFormation)로 Runtime을 올리던 때의 것이다. 그 Deploy 단계의 시간에는 CLI의 설치와 스택을 만드는 시간이, `make destroy`의 시간에는 스택을 지우는 시간이 들어 있다. 열 "지금의 배포 단계"는 코드를 묶어 `CreateAgentRuntime`이나 `UpdateAgentRuntime`을 부르는 지금의 코드로 같은 날 따로 잰 것이다. 그 실행의 첫 시도는 배포 역할의 권한이 모자라 Deploy에서 멈췄다(`make e2e` 12개 가운데 6개 통과, 401초). 권한을 고쳐 `make deploy`를 다시 돌린 두 번째 시도에서 `make e2e`가 12개 모두 통과했다. 빈 계정의 `make deploy`와 첫 `make seed`는 첫 시도의 값이고, 나머지는 두 번째 시도, 그 뒤의 확인 시험(`e2e_checks/spikes/spike_operations.py`, 새 버전의 심사), `make destroy`의 값이다. 같은 열의 "심사를 다진 뒤의 실행"은 같은 날 검사 목록(검사와 배포가 같은 줄을 쓴다), 좁힌 역할, 알림의 재시도, 건너뛰는 record를 넣은 코드로 빈 계정에서 `AUTO_APPROVE=1 make deploy seed e2e`와 `make destroy`를 돌린 값이다. 첫 번째 `make e2e`는 seed가 시작한 심사가 아직 돌고 있어 시작하지 않았고(아래 "`make e2e`가 확인하는 것"), 같은 명령을 다시 돌린 두 번째에 12개 모두 통과했다. 빈 계정의 `make deploy`와 첫 `make seed`는 첫 번째의 값, 나머지는 두 번째의 값이다.

| 순서 | 명령 | 하는 일 | 걸린 시간: CLI로 배포하던 때 | 걸린 시간: 지금의 배포 단계 |
|---|---|---|---|---|
| 1 | `make deploy` | 코드 묶음(`build/`)을 만들고 `terraform apply`로 허브의 틀을 올린다. 계획을 보여 주고 `yes`를 묻는다(확인하지 않았다). `AUTO_APPROVE=1`이면 묻지 않는다. | 빈 계정에서 226초(3분 46초, `AUTO_APPROVE=1`). 이미 올린 허브에 다시 올린 두 번은 11~12초였다(무엇이 바뀌었느냐에 따라 다르다). 고친 뒤의 실행에서는 빈 계정에서 227초 | 빈 계정에서 234초(3분 54초). 배포 역할의 정책만 바꿔 다시 올린 두 번은 11초와 10초. 심사를 다진 뒤의 실행에서는 빈 계정에서 235초(3분 55초), 바뀐 것 없이 다시 올릴 때 10초 |
| 2 | `make seed` | 공유 도구 record(`parts-tools`)를 카탈로그에 넣고 승인한다. 개발자의 첫 검색이 이것을 찾는다. 승인 요청이 호스팅 심사를 시작하지만, 심사는 AGENT가 아닌 record를 건너뛰고 알림 없이 끝난다(`Skipped`). | 6초 | record를 처음 만들 때 6초. 승인된 record가 이미 있으면 그대로 두고 1초. 심사를 다진 뒤의 실행에서는 6초와 2초. 처음 만들 때 시작한 심사는 1.7초 만에 `Skipped`로 끝났다 |
| 3 | `dev_team/agent_template/publish.sh dev_team/<에이전트> [변형]` (같은 일을 하는 `make publish AGENT=<에이전트>`는 확인하지 않았다) | 개발팀이 코드를 제출함에 올리고 신청서를 카탈로그에 쓰고 승인을 요청한다. 요청하면 호스팅 심사가 저절로 시작한다. 셸의 자격 증명으로 돌고, 개발팀 역할(`<prefix>-dev-role`)의 권한이면 된다(`make e2e`가 이 역할로 돌린다). | 명령은 6초. 심사는 통과할 때 409~490초(그 가운데 Deploy 단계가 310~363초), Scan에서 떨어질 때 30~33초. 세 번의 실행에서 잰 범위다. 고친 뒤의 실행에서는 통과 440초와 453초(Deploy 316초, 315초), Scan에서 떨어질 때 29초 | 명령은 6초. 심사는 통과할 때 356초와 385초(Deploy 254초, 255초), Scan에서 떨어질 때 31초. Deploy 단계의 대부분은 새 Runtime이 `READY`가 되기를 기다리는 시간이다(231~232초, 세 번). 코드 묶음은 `release_review` 31,584,418바이트, `quality_agent` 30,815,269바이트다. 승인된 에이전트의 새 버전(Runtime을 고친다)은 심사 308초와 296초(Deploy 266초, 244초)였고, 새 버전이 `READY`가 되기까지 241초와 221초였다. 심사를 다진 뒤의 실행에서는 명령 6초, 통과 370초와 387초(Scan 33초, 36초. Deploy 264초, 257초. 새 Runtime이 `READY`가 되기까지 242초, 231초), Scan에서 떨어질 때 32초 |
| 4 | `make e2e` | 흐름 1을 끝에서 끝까지 확인한다(아래). 두 에이전트를 제출하고, 심사, 승인, 반려, 재신청, 호출까지 본다. 기록은 `e2e_checks/last-run.log`에 남는다. | 고치기 전의 마지막 실행(`make e2e`, 12개 통과)에서 1555초(26분). 그 가운데 497초는 그 앞의 실행이 남긴 승인된 에이전트 둘을 먼저 지운 시간이다. 에이전트가 없는 허브라면 약 1058초로 본다(잰 값이 아니라 1555에서 497을 뺀 값). 그때까지 에이전트가 없는 허브에서 잰 것은 첫 실행의 966초뿐이었는데, 그 실행은 고치기 전의 스크립트를 `make e2e` 없이 돌렸고 12개 가운데 11개가 통과했다. 고친 뒤의 실행(`make e2e`, 12개 통과)은 에이전트가 없는 허브에서 996초(16분 36초)였다 | 857초(14분 17초, 12개 통과). 첫 시도가 남긴 두 에이전트의 역할, 정책, record를 먼저 지운 17초가 들어 있다(그때 남은 Runtime은 없었다). 심사를 다진 뒤의 실행에서는 에이전트가 없는 허브에서 853초(14분 13초, 12개 통과) |
| 5 | `make destroy` | 허브가 만든 것을 모두 지운다(아래). 계획을 보여 주고 `yes`를 묻는다(확인하지 않았다). | 승인된 에이전트 둘이 있는 허브에서 675초(11분 15초, `AUTO_APPROVE=1`). 대부분은 에이전트의 Runtime 스택을 지우는 시간(스택마다 4분 남짓)이다. 고친 뒤의 실행에서는 같은 허브에서 654초(10분 54초) | 승인된 에이전트 둘이 있는 허브에서 566초(9분 26초). 그 가운데 Runtime 둘을 지우는 시간이 약 195초씩이다(`DeleteAgentRuntime` 뒤 `DELETING`에서 사라지기까지). 심사를 다진 뒤의 실행에서는 같은 허브에서 576초(9분 36초). 그 가운데 에이전트 둘의 정리가 약 480초, `terraform destroy`가 85초 |

`make test`는 단위 시험이다(AWS를 부르지 않는다).

### `make e2e`가 확인하는 것

`e2e_checks/e2e_hosting.py`가 데모 스토리의 장면 1-1에서 2-3까지를 순서대로 돌리고 확인 열둘을 한 줄씩 찍는다(`[PASS]`, `[FAIL]`, 관찰은 `[INFO]`). 끝 줄은 `== N checks passed, M failed, K observations`다.

1. 개발팀 역할로 카탈로그를 검색하면 `parts-tools`가 나온다.
2. 개발팀 역할로 공유 도구를 부르면 답이 오고, 다른 도구는 정책으로 거부된다(JSON-RPC 오류 -32002, "policy enforcement").
3. 개발팀 역할로 `release_review`를 제출하면 record가 `PENDING_APPROVAL`이 된다.
4. 심사가 승인 요청에서 120초 안에 시작한다(`publish.sh`를 부르기 직전부터 잰다).
5. 심사가 `SUCCEEDED`이고 단계가 Read, Scan, Grant, Deploy, Entry, TestCall, Approve 순서다.
6. record가 `APPROVED`이고 검색된다.
7. 사용자가 에이전트 게이트웨이로 `release_review`를 부르면 200이고, 규칙을 어긴 변경에는 검토 요청 도구를 쓴다.
8. `quality_agent`의 취약한 변형(`v1-vulnerable`)은 심사가 Scan에서 멈추고 알림이 온다. 알림으로 에이전트와 단계를 알 수 있고, 알림이 가리키는 검사 로그에 `jinja2`의 취약점 줄이 있다.
9. 그 신청으로는 역할, 정책, target, Runtime이 만들어지지 않았다.
10. `reject.sh`로 반려하면 record가 `REJECTED`다.
11. 고친 버전을 다시 제출하면 심사가 다시 돌아 `SUCCEEDED`가 되고 record가 `APPROVED`다.
12. `quality_agent`가 두 도구를 써서 답한다.

스크립트는 시작할 때 두 에이전트를 리포의 정리 코드로 처음 상태로 돌려놓으므로(무엇을 지웠는지 찍는다) 실패한 뒤 다시 돌려도 된다(앞의 실행이 남긴 승인된 에이전트 둘을 지우고 다시 돈 것을 두 번 확인했다. 한 번은 실패한 실행 뒤였다). 심사가 돌고 있으면 바로 시작하지 않는다. 2026-11-22에 빈 계정에서 `make deploy seed e2e`를 돌렸을 때 이 거부가 나왔다. `make seed`가 공유 도구 record를 승인 요청 상태로 바꿔 시작한 심사(1.7초 만에 `Skipped`로 끝났다)가 `make e2e`가 시작한 순간에 아직 돌고 있었기 때문이다(`[FAIL] 0 no review is running`). 그 심사가 끝난 뒤 같은 명령을 다시 돌리면 `make seed`는 승인된 record를 그대로 두므로 심사가 시작하지 않고, `make e2e`가 돈다. 지금의 스크립트는 바로 거부하지 않는다. 도는 심사가 있으면 5초마다 다시 보며 60초까지 끝나기를 기다리고, 끝나면 기다린 시간과 실행 이름을 한 줄 찍고 시작한다. 60초가 지나도 돌고 있으면 위와 같이 거부한다. 스크립트가 본 뒤에야 시작하는 심사(그 이벤트가 아직 오지 않은 것)는 기다리지 못한다. seed의 심사라면 Read, `Reviewable`, `Skipped`를 지나며 공유 도구 record를 읽기만 하므로 정리나 확인과 부딪히지 않는다. 이 기다림은 AWS에서는 아직 돌려 보지 않았다(단위 시험 `tests/test_e2e_scripts.py`가 확인한다). 알림은 임시 SQS 큐(`<prefix>-e2e-alerts`)로 받고, 끝나면 큐와 구독을 지운다. 계정 ID는 `<ACCOUNT>`로 가려서 찍는다.

## 허브가 떠 있는 동안 요금이 드는 것

허브가 올리는 자원과, 각 서비스의 요금 방식으로 보아 요금이 드는 때다. 이 실행은 요금을 재지 않았으니 금액은 각 서비스의 요금 페이지를 본다. 허브는 켜 두는 서버가 없고, 대부분은 쓰는 만큼(호출 수, 실행 시간, 저장량) 요금이 붙는다.

| 자원 | 언제 요금이 드나 |
|---|---|
| Amazon Bedrock 모델(`MODEL_ID`) | 에이전트가 답할 때마다. 심사의 시험 호출과 `make e2e`의 호출도 포함된다. |
| AgentCore Runtime(승인된 에이전트마다 하나) | 에이전트가 호출을 처리하는 동안 |
| AgentCore Gateway 둘, Policy(policy engine과 가드레일 검사) | 호출과 권한 판단마다 |
| CodeBuild 프로젝트 둘 | 심사마다 build가 도는 분만큼. 이 실행에서 Scan 단계는 28~47초, Deploy 단계는 310~363초였다. 고친 뒤의 실행에서는 Scan 27~71초, Deploy 315~316초였다. Deploy의 값은 CLI로 배포하던 때의 것이다(위의 "다섯 명령"). 지금의 배포 단계에서는 Deploy 단계가 244~266초였고, 그 가운데 221~241초는 build가 Runtime이 `READY`가 되기를 기다린 시간이다. 심사를 다진 뒤의 실행에서는 Scan 31~36초, Deploy 257초와 264초(그 가운데 `READY`를 기다린 시간 231초와 242초)였다. |
| Lambda 일곱(심사 다섯, 샘플 도구 하나, 커스텀 가드레일의 interceptor 하나), Step Functions, EventBridge, SNS, SQS | 실행과 메시지마다. interceptor는 에이전트 게이트웨이에 붙어 있는 동안 호출마다 두 번(요청과 답) 돈다. |
| Amazon Bedrock Guardrails(커스텀 가드레일의 guardrail 하나) | interceptor가 붙어 있는 동안 호출마다 두 번(요청과 답) 검사한다. Amazon Bedrock 요금 페이지(2026-11-22에 읽었다)는 검사한 글의 양(text unit, 1,000자까지가 하나)을 필터마다 매기고, 이 guardrail이 쓰는 두 필터(낱말 필터, 정규식의 민감 정보 필터)는 무료라고 적는다. 여기서는 요금을 확인하지 않았다. |
| S3(제출함: 제출물과 에이전트의 코드 묶음), CloudWatch Logs | 저장량과 들어온 로그만큼. Terraform이 만드는 로그 그룹 열(Lambda 일곱, CodeBuild 둘, state machine 하나)은 14일 보관한다. Runtime이 만드는 로그 그룹(`/aws/bedrock-agentcore/runtimes/...`)에는 허브가 보관 기간을 정하지 않는다. 에이전트를 지울 때 함께 지운다. |
| CloudWatch 알람 하나(커스텀 가드레일의 `<prefix>-guardrail-errors`) | 알람이 있는 동안. CloudWatch 요금 페이지(2026-11-22에 읽었다)는 알람을 그 메트릭마다 시간 단위로 매기고, 무료 사용량(표준 해상도의 알람 메트릭 10개)이 있다고 적는다. 여기서는 확인하지 않았다. |
| AWS Agent Registry, SSM 값(표준), IAM | 요금이 드는지 확인하지 않았다 |

## `make destroy`가 지우는 것과 남기는 것

`make destroy`는 지울 것의 계획을 보여 주고 `yes`를 받은 뒤(이 실행은 `AUTO_APPROVE=1`로 묻지 않고 돌렸다) 여섯 번에 나눠 지운다.

1. 에이전트 게이트웨이에 붙은 커스텀 가드레일의 interceptor(Terraform 밖. `guardrail.sh attach`가 붙인다). 가장 먼저 떼므로, 게이트웨이가 지워진 Lambda를 가리키는 일이 없다. 허브가 올라와 있지 않거나 게이트웨이가 없으면 아무것도 하지 않는다. [커스텀 가드레일](platform_team/custom_guardrail/README.md#붙이고-떼는-명령)
2. 전사 정책의 모드(SSM `/<prefix>/policies/` 아래의 값. `rollout.sh`가 적는다). 에이전트보다 먼저 지우므로, 정리하는 동안 승인되는 에이전트에는 전사 정책이 걸리지 않는다. 정책 자체는 다음 단계가 에이전트와 함께 지운다. 이 단계는 아직 AWS에서 돌려 보지 않았다. [전사 정책](platform_team/company_policy/README.md#make-destroy)
3. 심사가 에이전트마다 만든 것(Terraform 밖): 정책 넷 이상(`entry_permit_`, `review_permit_`, `tool_`, `guard_secret_`, 운영 중에 더하면 `guard_prompt_`, `stop_agent_`), 에이전트 게이트웨이의 target, Runtime `<prefix>_<에이전트>`, Runtime의 로그 그룹, 제출함의 코드 묶음(`packages/<에이전트>/`), 실행 역할, SSM 값, 그리고 에이전트의 카탈로그 record. 순서와 이유는 [호스팅 심사, 반려](platform_team/hosting_review/README.md#지우는-것과-순서)에 있다. Runtime의 workload identity는 허브가 따로 지우지 않는다. CLI로 배포하던 때의 실행에서는 Runtime과 함께 사라졌다. API로 만든 Runtime에서도 2026-11-22의 실행에서 Runtime과 함께 사라졌다(`reject.sh` 한 번과 `make destroy`의 Runtime 둘, 목록으로 확인했다). 그 이름은 Runtime ID와 같다.
4. `make seed`가 넣은 공유 도구 record.
5. 그래도 카탈로그에 남은 record(AGENT가 아니거나 이름 규칙에 맞지 않아 3에서 찾지 못한 것). 종류와 이름에 상관없이 모두 지우고 하나씩 찍는다. 카탈로그는 허브의 것이고 다음 단계에서 지워진다.
6. `terraform destroy`: 게이트웨이 둘, policy engine과 그 정책, 카탈로그, Lambda, 커스텀 가드레일의 guardrail과 그 버전, CodeBuild 프로젝트, state machine, rule, 역할과 권한 경계, 제출함 bucket(모든 version까지), 알림 주제와 큐, 알람, SSM 값, 로그 그룹.

마지막에 `e2e_checks/check_cleanup.py`가 접두어로 시작하는 자원이 남았는지 종류마다 찾아보고 `still present: nothing`(또는 남은 종류)을 찍는다. 읽기만 한다.

허브는 CDK를 쓰지 않으므로 계정의 CDK bootstrap(스택 `CDKToolkit`과 그 bucket)에 손대지 않는다. CLI로 배포하던 때의 실행은 그 bucket에 에이전트 코드의 사본(에이전트마다 31 MB 남짓의 zip 하나)과 CDK template을 남겼다. 허브는 이 사본을 지우지 않는다.

CLI로 배포하던 때의 실행에서는 그 밖에 남은 것이 없었다. `check_cleanup.py`가 `still present: nothing`을 찍었고, 게이트웨이, 카탈로그, Runtime마다 서비스가 만든 workload identity도 그 주인과 함께 사라졌다(목록으로 확인했다). 지금의 배포로 만든 허브를 2026-11-22에 `make destroy`로 지웠을 때도(승인된 에이전트 둘, 그 가운데 하나는 Runtime 버전 3) `check_cleanup.py`가 `still present: nothing`을 찍었다. 이름이 `AgentCore-`로 시작하는 스택, `hub_`로 시작하는 Runtime과 workload identity, 제출함 bucket(그래서 `packages/` 아래의 묶음)도 남지 않았고, 계정의 `CDKToolkit` 스택은 그대로 있었다(목록으로 확인했다). 심사를 다진 뒤의 실행(제출함에 bucket 정책이 있다)에서도 `make destroy`가 `still present: nothing`을 찍었고, `hub_`로 시작하는 Runtime과 workload identity가 남지 않았고, `CDKToolkit` 스택은 그대로 있었다(목록으로 확인했다).

## 알려진 한계

각 기능의 문서에 있다.

- 배포 단계의 권한: 검사(Scan)의 역할은 제출물을 읽기만 한다. 배포(Deploy)의 역할은 Runtime을 만들 수 있고(정책은 만들기를 `runtime/*`에 허락한다. IAM이 만들기를 그 자원에 대어 보므로 자원으로는 허브의 이름으로 좁히지 못했다. 조건 키는 찾아보지 않았다), 허브의 Runtime을 고치고 읽을 수 있고, Runtime에 이름이 `<prefix>-agent-*-role`인 역할을 넘길 수 있고, Runtime ARN을 SSM에 쓸 수 있다(정책이 허락하는 SSM 값은 `/<prefix>/agents/<에이전트>/runtime_arn`뿐이다). 역할, 정책, target을 만들거나 record를 승인하지는 못한다. Grant는 이 이름의 역할을 권한 경계를 달아서만 만든다. 허브 밖에서 이 이름으로 만든 역할에는 경계가 없을 수 있지만, 그런 역할을 만들려면 계정의 IAM 권한이 있어야 하고 심사의 역할 가운데 그 권한을 가진 것은 없다. 남는 한계는 둘이다. 배포 역할 하나가 모든 심사에 쓰이므로, 배포 build 안에서 코드를 실행할 수 있으면 허브의 다른 에이전트의 Runtime을 바꾸거나, 다른 에이전트의 실행 역할을 넘기거나, 다른 에이전트의 `runtime_arn`을 쓸 수 있다(Entry는 그 에이전트의 Runtime이 아닌 ARN을 거부한다). 또 정책은 이름이 `<prefix>_`로 시작하지 않는 Runtime의 만들기를 막지 않으므로, 그런 코드가 다른 이름의 Runtime을 만들 길이 열려 있다. 그런 만들기가 실제로 되는지는 해 보지 않았다. 그런 Runtime이 생기면 허브의 정리는 그것을 지우지 않는다. [호스팅 심사, 알려진 한계](platform_team/hosting_review/README.md#알려진-한계-배포-단계의-권한)
- 시험 호출은 HTTP 상태만 보고 답의 내용은 보지 않는다. [호스팅 심사, 시험 호출](platform_team/hosting_review/README.md#알려진-한계-시험-호출)
- 승인된 에이전트의 새 버전: Deploy가 끝나면 돌고 있는 코드가 새 버전으로 바뀌고(2026-11-22의 실행에서 본 것), 그 뒤의 단계가 실패해도 되돌리지 않는다. 빠진 도구의 정책은 Grant에서 사라진다. 새 버전을 반려하면 record만 `REJECTED`가 되고 돌고 있는 에이전트는 그대로다. 같은 record의 심사 둘이 겹치면 뒤의 것이 Read에서 멈춘다. 이 셋은 코드가 그렇게 하고, AWS에서는 해 보지 않았다. Read의 역할은 record를 읽고(`GetRegistryRecord`), 같은 record의 앞선 심사를 찾으려고 이 state machine의 실행을 나열하고 그 입력을 읽는다(`states:ListExecutions`, `states:DescribeExecution`). 바꾸는 것은 없다. [호스팅 심사, 승인된 에이전트의 새 버전](platform_team/hosting_review/README.md#승인된-에이전트의-새-버전)
- 반려의 한계: 심사가 도는 동안에는 반려가 거부한다. [호스팅 심사, 반려의 한계](platform_team/hosting_review/README.md#한계)
- 개발팀 역할의 카탈로그 권한은 모든 record에 걸린다. [개발팀의 권한](platform_team/dev_access/README.md#카탈로그-권한의-범위)
- 간접 의존성은 검사한 것과 배포한 것이 같다고 보장되지 않는다. `requirements.txt`에 적은 줄은 검사와 배포가 같은 파일을 쓴다. [호스팅 심사, requirements.txt 규칙](platform_team/hosting_review/README.md#requirementstxt-규칙)
- `release_review`의 판정은 모델 호출 한 번이다. [release_review, 한계](dev_team/release_review/README.md#한계)
- 커스텀 가드레일: interceptor Lambda가 실패하는 동안 에이전트 게이트웨이는 모든 요청을 거부한다(알람이 알린다). 스트리밍 응답과, 에이전트를 둔 게이트웨이 너머의 호출은 이 리포의 코드로 확인하지 않았다. [커스텀 가드레일](platform_team/custom_guardrail/README.md#확인한-것과-하지-않은-것)
- 에이전트 멈추기: 에이전트 게이트웨이의 진입만 막으므로 Runtime을 직접 부르는 길은 남는다. harness 에이전트는 진입 target이 없어 이 명령으로 멈출 수 없다. 30분보다 오래 돌고 있는 세션은 찾지 못할 수 있다. `stop.sh`와 `resume.sh`는 아직 AWS에서 돌려 보지 않았다. [에이전트 멈추기와 재개, 한계](platform_team/agent_stop/README.md#한계)
