# AI 에이전트 호스팅 허브

Amazon Bedrock AgentCore 위에서 여러 개발팀의 AI 에이전트를 한곳에 올리고 관리하는 허브를 만든다.
플랫폼팀은 허브(게이트웨이, 정책, 레지스트리)를 만들고, 개발팀은 에이전트를 만들어 허브에 올린다.
정책은 Cedar로 쓰고, 어떤 에이전트가 어떤 도구를 쓸 수 있는지 허브가 정한다.

> 만드는 중입니다. 지금 들어 있는 것은 흐름 1(호스팅: 신청, 심사, 승인, 반려와 재신청)입니다. 흐름 2(운영)는 다음 계획에서 더합니다.

## 무엇이 들어 있나

| 폴더 | 누가 쓰나 | 내용 |
|---|---|---|
| `platform_team/` | 플랫폼팀 | 허브의 틀. 기능마다 폴더 하나와 그 안의 Terraform 모듈이다. [게이트웨이 둘](platform_team/agent_gateway/README.md)([도구 쪽](platform_team/tool_gateway/README.md)), [전사 정책](platform_team/company_policy/README.md), [카탈로그](platform_team/agent_catalog/README.md), [호스팅 심사](platform_team/hosting_review/README.md), [샘플 사내 도구](platform_team/sample_tools/README.md), [모니터링](platform_team/agent_monitoring/README.md), [개발팀의 권한](platform_team/dev_access/README.md) |
| `dev_team/` | 개발팀 | [에이전트 템플릿](dev_team/agent_template/README.md)과 올리는 명령(`publish.sh`), 예시 에이전트 둘: [release_review](dev_team/release_review/README.md)(LangGraph), [quality_agent](dev_team/quality_agent/README.md)(Strands) |
| `e2e_checks/` | 누구나 | 실제 AWS에서 돌리는 확인 스크립트. `e2e_hosting.py`(흐름 1의 끝에서 끝까지), `check_platform.py`(허브의 틀), `check_cleanup.py`(지운 뒤 남은 것) |
| `tests/` | 누구나 | 단위 시험(`make test`). AWS를 부르지 않는다. |

## 사전 요건

- Terraform 1.9 이상, Python 3.12 이상과 [uv](https://docs.astral.sh/uv/), bash
- AWS 자격 증명. 허브는 IAM 역할, 정책 엔진, 게이트웨이, Lambda, CodeBuild, Step Functions, S3 bucket 등을 만든다. 이 문서의 시간은 관리자 권한의 자격 증명으로 잰 것이다.
- 리전 `us-west-2`. 셸의 기본 리전이 다르면 `AWS_REGION=us-west-2`(도구에 따라 `AWS_DEFAULT_REGION`도)를 준다. 리전, 접두어, 모델은 `.env`로도 정할 수 있다(아래 "`.env`").
- Amazon Bedrock 모델 사용 권한. 에이전트가 부르는 모델은 `MODEL_ID`(기본값은 추론 프로파일 `us.anthropic.claude-haiku-4-5-20251001-v1:0`)다.
- CDK bootstrap. 심사의 배포 단계가 AgentCore CLI(`agentcore deploy`, CDK)로 Runtime을 올리므로 계정과 리전에 기본 qualifier(`hnb659fds`)의 bootstrap 스택 `CDKToolkit`이 있어야 한다. 없으면 `npx aws-cdk bootstrap aws://<ACCOUNT>/us-west-2`로 만든다(이 실행은 계정에 이미 있던 bootstrap을 썼고, 이 명령은 확인하지 않았다). 리포의 명령은 로컬에서 Node.js를 쓰지 않는다. CLI는 CodeBuild 안에서 설치된다.
- CloudWatch Transaction Search. 배포 build의 AgentCore CLI가 "enabling CloudWatch Transaction Search"를 찍는다. 이 실행의 계정에는 이미 켜져 있었고, 배포 역할은 그 설정을 읽기만 할 수 있다(`xray:GetTraceSegmentDestination`). 꺼진 계정에서 어떻게 되는지는 확인하지 않았다.

### `.env`

`.env.example`을 `.env`로 복사하면 허브의 세 값, 리전(`AWS_REGION`), 접두어(`DEMO_PREFIX`), 모델(`MODEL_ID`)을 거기서 읽는다. `make`, `publish.sh`, `reject.sh`, `e2e_checks/e2e_hosting.py`가 모두 같은 규칙을 따른다.

- `.env`에서 읽는 것은 이 세 줄뿐이다. 다른 줄은 읽지도 내보내지도 않는다. 그래서 `.env`에 자격 증명을 적어 두어도 명령이 쓰는 자격 증명은 바뀌지 않는다.
- 한 줄에 `이름=값`으로 쓴다. 따옴표, `export`, `=` 앞뒤의 빈칸은 쓰지 않는다. `make`와 셸은 따옴표를 다르게 읽기 때문이다. 같은 이름이 두 번 나오면 마지막 줄을 쓴다.
- 어느 값을 쓰나: `make`의 명령줄에 준 값(`make deploy DEMO_PREFIX=demo`)이 가장 앞서고, 그다음이 `.env`, 그다음이 셸의 환경 변수, 마지막이 기본값(`us-west-2`, `hub`, 아래의 모델)이다. `make`가 부르는 명령(`make publish`, `make e2e`)은 `make`가 정한 값을 그대로 쓰고 `.env`를 다시 읽지 않는다(그 표시가 `HUB_ENV_LOADED=1`이다). `publish.sh`, `reject.sh`, `e2e_hosting.py`를 직접 부르면 같은 규칙으로 `.env`를 읽는다. `e2e_hosting.py`가 부르는 두 명령은 그 스크립트가 정한 값을 쓴다.
- 접두어는 소문자로 시작하는 2~10자의 소문자와 숫자다(`hub`, `demo2`). 정책 엔진, CLI 프로젝트, 게이트웨이, bucket의 이름이 접두어로 시작하는데, 그 이름들의 규칙을 모두 지키는 모양이 이것이다. 다른 모양이면 Terraform(`make deploy`)과 Python 명령이 아무것도 만들기 전에 거부한다.

이 규칙은 단위 시험(`tests/test_hub_env.py`)으로 확인했다. AWS에서는 `.env` 없이 셸의 `AWS_REGION`과 기본값으로만 돌렸으므로, `.env`를 읽는 길은 AWS에서 확인하지 않았다.

## 다섯 명령

시간은 2026-11-22의 실행(`us-west-2`, 접두어 `hub`)에서 잰 것이다. `make deploy`와 `make destroy`는 `AUTO_APPROVE=1`로 돌렸으므로 `yes`를 묻는 대화는 확인하지 않았다.

| 순서 | 명령 | 하는 일 | 걸린 시간 |
|---|---|---|---|
| 1 | `make deploy` | 코드 묶음(`build/`)을 만들고 `terraform apply`로 허브의 틀을 올린다. 계획을 보여 주고 `yes`를 묻는다(확인하지 않았다). `AUTO_APPROVE=1`이면 묻지 않는다. | 빈 계정에서 226초(3분 46초, `AUTO_APPROVE=1`). 정책 하나나 state machine 하나만 바뀌었을 때 다시 올리면 11~12초 |
| 2 | `make seed` | 공유 도구 record(`parts-tools`)를 카탈로그에 넣고 승인한다. 개발자의 첫 검색이 이것을 찾는다. | 6초 |
| 3 | `dev_team/agent_template/publish.sh dev_team/<에이전트> [변형]` (같은 일을 하는 `make publish AGENT=<에이전트>`는 확인하지 않았다) | 개발팀이 코드를 제출함에 올리고 신청서를 카탈로그에 쓰고 승인을 요청한다. 요청하면 호스팅 심사가 저절로 시작한다. 셸의 자격 증명으로 돌고, 개발팀 역할(`<prefix>-dev-role`)의 권한이면 된다(`make e2e`가 이 역할로 돌린다). | 명령은 6초. 심사는 통과할 때 409~490초(그 가운데 Deploy 단계가 310~363초), Scan에서 떨어질 때 30~33초. 세 번의 실행에서 잰 범위다 |
| 4 | `make e2e` | 흐름 1을 끝에서 끝까지 확인한다(아래). 두 에이전트를 제출하고, 심사, 승인, 반려, 재신청, 호출까지 본다. 기록은 `e2e_checks/last-run.log`에 남는다. | 마지막 실행(`make e2e`, 12개 통과)에서 1555초(26분). 그 가운데 497초는 앞의 실행이 남긴 승인된 에이전트 둘을 먼저 지운 시간이다. 에이전트가 없는 허브라면 약 1058초로 본다(잰 값이 아니라 1555에서 497을 뺀 값). 에이전트가 없는 허브에서 잰 것은 첫 실행의 966초뿐인데, 그 실행은 고치기 전의 스크립트를 `make e2e` 없이 돌렸고 12개 가운데 11개가 통과했다 |
| 5 | `make destroy` | 허브가 만든 것을 모두 지운다(아래). 계획을 보여 주고 `yes`를 묻는다(확인하지 않았다). | 승인된 에이전트 둘이 있는 허브에서 675초(11분 15초, `AUTO_APPROVE=1`). 대부분은 에이전트의 Runtime 스택을 지우는 시간(스택마다 4분 남짓)이다 |

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

스크립트는 시작할 때 두 에이전트를 리포의 정리 코드로 처음 상태로 돌려놓으므로(무엇을 지웠는지 찍는다) 실패한 뒤 다시 돌려도 된다(앞의 실행이 남긴 승인된 에이전트 둘을 지우고 다시 돈 것을 두 번 확인했다. 한 번은 실패한 실행 뒤였다). 심사가 돌고 있으면 시작하지 않는다(이 거부는 실행해 보지 않았다). 알림은 임시 SQS 큐(`<prefix>-e2e-alerts`)로 받고, 끝나면 큐와 구독을 지운다. 계정 ID는 `<ACCOUNT>`로 가려서 찍는다.

## 허브가 떠 있는 동안 요금이 드는 것

허브가 올리는 자원과, 각 서비스의 요금 방식으로 보아 요금이 드는 때다. 이 실행은 요금을 재지 않았으니 금액은 각 서비스의 요금 페이지를 본다. 허브는 켜 두는 서버가 없고, 대부분은 쓰는 만큼(호출 수, 실행 시간, 저장량) 요금이 붙는다.

| 자원 | 언제 요금이 드나 |
|---|---|
| Amazon Bedrock 모델(`MODEL_ID`) | 에이전트가 답할 때마다. 심사의 시험 호출과 `make e2e`의 호출도 포함된다. |
| AgentCore Runtime(승인된 에이전트마다 하나) | 에이전트가 호출을 처리하는 동안 |
| AgentCore Gateway 둘, Policy(policy engine과 가드레일 검사) | 호출과 권한 판단마다 |
| CodeBuild 프로젝트 둘 | 심사마다 build가 도는 분만큼. 이 실행에서 Scan 단계는 28~47초, Deploy 단계는 310~363초였다. |
| Lambda 여섯(심사 다섯, 샘플 도구 하나), Step Functions, EventBridge, SNS, SQS | 실행과 메시지마다 |
| S3(제출함, CDK bootstrap bucket의 사본), CloudWatch Logs | 저장량과 들어온 로그만큼. Terraform이 만드는 로그 그룹 아홉(Lambda 여섯, CodeBuild 둘, state machine 하나)은 14일 보관한다. Runtime이 만드는 로그 그룹(`/aws/bedrock-agentcore/runtimes/...`)에는 허브가 보관 기간을 정하지 않는다. 에이전트를 지울 때 함께 지운다. |
| AWS Agent Registry, SSM 값(표준), IAM | 요금이 드는지 확인하지 않았다 |

## `make destroy`가 지우는 것과 남기는 것

`make destroy`는 지울 것의 계획을 보여 주고 `yes`를 받은 뒤(이 실행은 `AUTO_APPROVE=1`로 묻지 않고 돌렸다) 네 번에 나눠 지운다.

1. 심사가 에이전트마다 만든 것(Terraform 밖): 정책 넷 이상(`entry_permit_`, `review_permit_`, `tool_`, `guard_secret_`), 에이전트 게이트웨이의 target, Runtime이 든 CloudFormation 스택 `AgentCore-<prefix><에이전트>-default`, Runtime의 로그 그룹, 실행 역할, SSM 값, 그리고 에이전트의 카탈로그 record. 순서와 이유는 [호스팅 심사, 반려](platform_team/hosting_review/README.md#지우는-것과-순서)에 있다. Runtime의 workload identity는 Runtime과 함께 사라졌다.
2. `make seed`가 넣은 공유 도구 record.
3. 그래도 카탈로그에 남은 record(AGENT가 아니거나 이름 규칙에 맞지 않아 1에서 찾지 못한 것). 종류와 이름에 상관없이 모두 지우고 하나씩 찍는다. 카탈로그는 허브의 것이고 다음 단계에서 지워진다.
4. `terraform destroy`: 게이트웨이 둘, policy engine과 그 정책, 카탈로그, Lambda, CodeBuild 프로젝트, state machine, rule, 역할과 권한 경계, 제출함 bucket(모든 version까지), 알림 주제와 큐, SSM 값, 로그 그룹.

마지막에 `e2e_checks/check_cleanup.py`가 접두어로 시작하는 자원이 남았는지 종류마다 찾아보고 `still present: nothing`(또는 남은 종류)을 찍는다. 읽기만 한다.

남기는 것: CDK가 계정의 CDK bootstrap bucket(`cdk-hnb659fds-assets-<ACCOUNT>-<region>`)에 올린 에이전트 코드의 사본. 이 bucket은 다른 스택과 함께 쓰므로 허브가 지우지 않는다. CDK bootstrap 스택 `CDKToolkit`도 허브가 만든 것이 아니므로 그대로 둔다. 이 실행에서 남은 것은 에이전트 코드의 zip 둘(에이전트마다 하나, 31 MB 남짓)과 CDK template 둘이었다. 같은 코드를 다시 올리면 같은 사본을 다시 쓴다.

그 밖에는 남지 않았다. `check_cleanup.py`가 `still present: nothing`을 찍었고, 게이트웨이, 카탈로그, Runtime마다 서비스가 만든 workload identity도 그 주인과 함께 사라졌다(목록으로 확인했다).

## 알려진 한계

각 기능의 문서에 있다.

- 배포 단계의 권한: CDK bootstrap 역할을 거치므로 배포 단계에서는 역할을 나눈 효과가 약하다. [호스팅 심사, 알려진 한계](platform_team/hosting_review/README.md#알려진-한계-배포-단계의-권한)
- 시험 호출은 HTTP 상태만 보고 답의 내용은 보지 않는다. [호스팅 심사, 시험 호출](platform_team/hosting_review/README.md#알려진-한계-시험-호출)
- 반려의 한계: 심사가 도는 동안에는 반려가 거부한다. 이미 승인된 에이전트의 새 버전에는 반려를 쓰지 않는다. [호스팅 심사, 반려의 한계](platform_team/hosting_review/README.md#한계)
- 개발팀 역할의 카탈로그 권한은 모든 record에 걸린다. [개발팀의 권한](platform_team/dev_access/README.md#카탈로그-권한의-범위)
- 간접 의존성은 검사한 것과 배포한 것이 같다고 보장되지 않는다. [런타임 뼈대, requirements.txt 규칙](platform_team/hosting_review/runtime_skeleton/README.md#requirementstxt-규칙)
- `release_review`의 판정은 모델 호출 한 번이다. [release_review, 한계](dev_team/release_review/README.md#한계)
