# 호스팅 심사

개발팀이 제출한 에이전트를 자동으로 심사하고, 통과하면 배포하고 승인합니다. 카탈로그의 레코드가 승인 요청 상태(`PENDING_APPROVAL`)가 되면 EventBridge rule `<prefix>-on-submit`이 Step Functions의 state machine `<prefix>-review`를 시작합니다. state machine은 순서와 실패했을 때의 갈림만 맡고, 일은 단계마다 Lambda 함수나 CodeBuild 프로젝트가 합니다.

## 개념도에서의 위치

[개념도](../../docs/hosting-hub-concept.png)의 흐름 1의 "호스팅 심사" 상자입니다. ③ "심사 시작"에서 시작해 ④ "에이전트에 도구 권한 부여"(Grant), ⑤ "에이전트 배포"(Deploy), ⑥의 6a "요청 허용"과 6b "승인 표시"(Approve)를 하고, 실패하면 ④-1 "심사 실패 알림"(점선)으로 빠집니다. Read와 Scan은 상자 안의 "자동 점검"입니다.

## 흐름

```
개발팀: publish.sh my_agent
  │  카탈로그 레코드 → PENDING_APPROVAL
  ▼
EventBridge rule <prefix>-on-submit
  │
  ▼
Step Functions <prefix>-review   (순서와 실패 갈림만 맡고, 일은 단계마다 따로 합니다)
  │
  ├─1 Read      Lambda     신청서를 확인합니다 (이름, 칸의 모양, 정책 이름 48자)
  ├─2 Scan      CodeBuild  제출 코드를 풀어 검사합니다 (requirements.txt 규칙, pip-audit)
  ├─3 Grant     Lambda     실행 역할과 도구 정책을 만듭니다 (권한 경계 안에서만)
  ├─4 Deploy    CodeBuild  Runtime <prefix>_<에이전트>를 만들거나 고칩니다
  ├─5 Entry     Lambda     에이전트 게이트웨이에 target을 만들고 review_permit, guard_secret을 겁니다
  ├─6 TestCall  Lambda     에이전트를 두 번 불러 봅니다
  └─7 Approve   Lambda     entry_permit을 걸고 레코드를 APPROVED로 바꿉니다
                   │
                   ▼
           사용자가 에이전트를 부를 수 있습니다

어느 단계든 실패하면
  → 알림 주제 <prefix>-alerts: "Hosting review failed at <단계>"
  → 레코드는 PENDING_APPROVAL에 남고, 허브는 되돌리지 않습니다
  → 플랫폼팀: reject.sh <에이전트> "<사유>" → REJECTED가 되고, 심사가 남긴 것을 지웁니다
```

제출된 코드를 여는 단계와 권한을 주는 단계를 나눴습니다. 그래서 제출된 코드가 스스로 권한을 얻을 수 없습니다.

```
제출된 코드를 여는 단계      Scan, Deploy  (CodeBuild)
  └─ 역할에 권한을 주는 action이 없습니다
     → 코드에 무엇이 들어 있어도 권한을 만들 수 없습니다

권한을 주는 단계             Grant, Entry, Approve  (Lambda)
  └─ 제출된 코드를 열지 않습니다
     → 신청서에 적힌 칸만 보고 권한을 줍니다

같은 코드
  └─ Scan과 Deploy는 신청서에 적힌 S3 object version 하나만 읽습니다
     → 검사한 코드와 배포하는 코드가 같습니다
```

실패했을 때 남는 것과 할 일은 [심사가 실패했을 때](#심사가-실패했을-때)와 [반려](#반려)에 있습니다.

## 일곱 단계

| # | 단계 | AWS 서비스 | 하는 일 | 실패하는 경우 |
|---|---|---|---|---|
| 1 | Read | Lambda `<prefix>-review-read` | 레코드를 읽고 신청서를 확인합니다. 다음 단계에는 확인한 칸만 넘깁니다. | 신청서의 이름이 레코드의 이름과 다를 때, 칸의 모양이 틀렸을 때, 정책 이름이 48자를 넘을 때, 같은 레코드의 앞선 심사가 아직 돌 때 |
| 2 | Scan | CodeBuild `<prefix>-review-scan` | 신청서에 적힌 version의 제출물을 풀어 모양과 `requirements.txt`를 확인하고, `pip-audit`(2.10.1로 고정)로 검사합니다. | 위험한 경로가 있을 때, `main.py`나 `requirements.txt`가 없을 때, 규칙에 맞지 않는 줄이 있을 때, `pip-audit`가 알려진 취약점을 찾을 때 |
| 3 | Grant | Lambda `<prefix>-review-grant` | 실행 역할 `<prefix>-agent-<에이전트>-role`을 권한 경계를 달아 만듭니다. 신청서의 도구마다 도구 정책을 걸고, 신청서에 없는 도구의 정책은 지웁니다. | 도구 정책이 `ACTIVE`가 되지 않을 때 |
| 4 | Deploy | CodeBuild `<prefix>-review-deploy` | 코드와 의존성을 묶어 Runtime `<prefix>_<에이전트>`를 만들거나 고치고, Runtime ARN을 SSM에 씁니다. | 의존성을 Runtime 플랫폼의 wheel로 받지 못할 때, Runtime이 `…FAILED`로 끝나거나 900초 안에 `READY`가 되지 않을 때 |
| 5 | Entry | Lambda `<prefix>-review-entry` | SSM의 Runtime ARN이 이 에이전트의 것인지 확인합니다. 에이전트 게이트웨이에 target을 만들고 `review_permit_<에이전트>`와 `guard_secret_<에이전트>`를 겁니다. | ARN이 이 에이전트의 Runtime이 아닐 때, 같은 이름의 target이 다른 Runtime을 가리킬 때 |
| 6 | TestCall | Lambda `<prefix>-review-testcall` | 에이전트 게이트웨이로 에이전트를 두 번 부릅니다. 승인 전에 에이전트를 부를 수 있는 것은 이 역할뿐입니다. | 보통 질문에 200이 오지 않을 때, 예시 access key가 든 질문이 403으로 거부되지 않을 때 |
| 7 | Approve | Lambda `<prefix>-review-approve` | 레코드를 다시 확인하고, 켜진 전사 정책과 사용자를 들이는 `entry_permit_<에이전트>`를 건 뒤 레코드를 `APPROVED`로 바꿉니다. | 심사 중에 신청서가 바뀌었거나 레코드가 반려됐을 때, 같은 이름의 전사 정책이 다른 모드로 있을 때 |

- AGENT가 아닌 레코드(공유 도구)와 신청서의 `framework`가 `harness`인 레코드는 Read가 건너뜁니다. 심사는 `Skipped`로 끝나고 알림은 가지 않습니다.
- 제출된 코드를 다루는 Scan과 Deploy의 역할에는 권한을 주는 action이 없습니다. 권한을 주는 Lambda 단계는 제출된 코드를 열지 않습니다.
- 단계마다 역할이 따로 있고, 이름은 함수나 프로젝트의 이름 뒤에 `-role`을 붙인 것입니다(`<prefix>-review-read-role`).

## 정책 이름

이름은 `platform_team/company_policy/policy_names.py` 한 곳에서 만듭니다.

| 이름 | 거는 곳 | 하는 일 |
|---|---|---|
| `tool_<에이전트>_<Target>_<도구>` | Grant | 에이전트가 이 도구를 부를 수 있습니다(도구 게이트웨이). |
| `review_permit_<에이전트>` | Entry | 승인 전에는 심사의 시험 호출만 에이전트를 부를 수 있습니다. |
| `guard_secret_<에이전트>` | Entry | 비밀값이 든 질문을 거부합니다. |
| `guard_prompt_<에이전트>` | 운영, Approve | 프롬프트 공격인 질문을 거부하는 전사 정책입니다([전사 정책 켜고 끄기](../company_policy/README.md#전사-정책-켜고-끄기)). |
| `stop_agent_<에이전트>` | 운영 | 시험 호출 말고는 모든 호출을 거부합니다. `agent_stop/stop.sh`로 걸고 `agent_stop/resume.sh`로 지웁니다. |
| `entry_permit_<에이전트>` | Approve | 사용자가 에이전트를 부를 수 있습니다. |

policy engine은 정책 이름을 48자까지 받습니다. `publish.sh`와 Read가 한도를 넘는 이름이 생기는 신청서를 거부하고, 에이전트 이름이 몇 자까지 될 수 있는지 알려 줍니다. 에이전트 이름은 소문자로 시작하는 소문자와 숫자의 마디를 밑줄 하나로 이은 것입니다(`quality_agent`, 3~31자).

## 제출 버킷과 배포 build

제출 버킷은 S3 bucket `<prefix>-<account>-<region>`입니다. 버전 관리를 켜 두었고, bucket 정책이 TLS로 오지 않은 요청을 거부합니다. TLS가 아닌 요청은 보내 보지 않았습니다. 개발팀은 `submissions/` 아래에 코드를 올리고 신청서에 그 object의 version을 적습니다. Scan과 Deploy는 꼭 그 version을 읽으므로 검사한 코드와 배포하는 코드가 같습니다.

배포 build(`deploy_build.py`)는 이 순서로 합니다.

1. 제출물을 풀고 `pyproject.toml`, `uv.lock`, `uv.toml`, `.python-version`을 지웁니다. uv는 설정 파일을 읽지 않습니다(`UV_NO_CONFIG=1`).
2. 의존성을 Runtime의 플랫폼(Linux arm64, CPython 3.13)용 wheel로만 받습니다.
3. 받은 의존성과 제출물의 맨 위 `.py` 파일을 zip 하나로 묶어 `packages/<에이전트>/<code version>.zip`에 올립니다. 하위 폴더와 `.py`가 아닌 파일은 넣지 않습니다.
4. Runtime `<prefix>_<에이전트>`가 없으면 만들고(`CreateAgentRuntime`) 있으면 고친 뒤(`UpdateAgentRuntime`), 새 버전이 `READY`가 되기를 기다립니다. Runtime에는 코드 패키지의 object version까지 넘깁니다.
5. Runtime ARN을 SSM `/<prefix>/agents/<에이전트>/runtime_arn`에 씁니다.

Runtime은 `PYTHON_3_13`에서 진입점 `["opentelemetry-instrument", "main.py"]`로 돌고, trace를 냅니다([모니터링](../agent_monitoring/README.md#에이전트의-trace)). 환경 변수는 `HUB_REGION`, `TOOL_GATEWAY_URL`, `MODEL_ID`, `AGENT_NAME`입니다.

## `requirements.txt` 규칙

패키지 색인에 있는 패키지를 이름, extras, 버전으로만 적습니다. Scan은 pip 옵션(`-r`, `-e`, `--index-url`, `--hash`), 직접 참조(`pkg @ URL`, URL, `file:`, 로컬 경로), 환경 표시(`; python_version >= "3.10"` 같은 것)를 거부합니다.

Scan과 Deploy는 규칙에 맞는 줄을 같은 함수(`submission_check.requirements_from`)로 다시 쓴 파일을 씁니다. 그래서 적힌 패키지는 Scan이 모두 검사하고 Deploy가 모두 설치합니다. 두 단계 모두 기본 색인(PyPI)에서 wheel만 받고, sdist의 `setup.py`는 실행하지 않습니다.

- 버전을 범위로 적으면 두 단계가 따로 고릅니다. `==`로 고정해야 검사한 버전과 같아집니다.
- 간접 의존성은 검사한 것과 설치한 것이 같다고 보장되지 않습니다. 운영 환경이라면 Scan이 `uv pip compile`로 간접 의존성까지 고정한 목록을 만들고, Deploy가 그 목록을 그대로 설치하게 합니다.

## 승인된 에이전트의 새 버전

팀이 승인된 에이전트를 다시 제출하면 같은 심사가 같은 이름으로 돕니다. 역할, Runtime, target, 정책은 있는 것을 고쳐 씁니다.

- Grant: 실행 역할의 inline 정책을 그때의 `MODEL_ID`로 다시 쓰고, 도구 정책을 새 신청서에 맞춥니다. 도구 정책은 실행 역할을 가리키므로 돌고 있는 버전에도 바로 닿습니다.
- Deploy: Runtime을 고칩니다. 이전 버전의 `entry_permit_<에이전트>`가 남아 있으므로, 그 뒤의 사용자 호출은 시험 호출을 지나기 전의 새 코드에 닿습니다.
- Approve: 이전 버전의 `entry_permit_<에이전트>`를 그대로 쓰고, 실패해도 지우지 않습니다.
- 뒤의 단계가 실패해도 허브는 되돌리지 않습니다. 되돌리는 코드가 없습니다.

2026-11-22의 실행에서 새 버전의 심사는 약 5분(296~308초)이었고, 심사가 끝난 뒤 DEFAULT endpoint의 `liveVersion`이 새 버전이었습니다. Deploy가 끝난 순간은 따로 보지 않았습니다. 도구가 바뀌는 새 버전, 떨어지는 새 버전, 겹치는 심사, 심사 중의 사용자 호출은 코드가 그렇게 하고 AWS에서는 해 보지 않았습니다.

## 심사가 실패했을 때

어느 단계든 실패하면 알림 주제 `<prefix>-alerts`에 알리고 심사를 멈춥니다. 알림의 제목은 `Hosting review failed at <단계>`이고, 내용은 실패한 단계(`failedStep`)와 오류(`error`)를 담은 심사의 상태입니다. Scan이나 Deploy면 `error`에 build 로그의 로그 그룹과 stream이 있습니다.

레코드는 `PENDING_APPROVAL`에 남고, 앞의 단계가 만든 것과 바꾼 것도 남습니다. 허브는 되돌리지 않습니다. 아래 표는 코드가 하는 일이고, AWS에서 해 본 것은 따로 적었습니다. Grant 뒤에서 떨어졌으면 알림에 `entryPermitBefore`가 있습니다. `true`면 이 심사 전부터 `entry_permit_<에이전트>`가 있었고, 보통 승인된 버전이 돌고 있습니다.

| 떨어진 단계 | 처음 올리는 에이전트 | 승인된 에이전트의 새 버전 |
|---|---|---|
| Read, Scan | 만든 것이 없습니다. | 바뀐 것이 없습니다. |
| Grant | 실행 역할과 Grant가 멈춘 데까지의 도구 정책. 사용자는 들어오지 못합니다. | 이전 버전의 코드가 Grant가 바꾼 역할과 도구 정책으로 돕니다. |
| Deploy | 위의 것과 코드 패키지, Deploy가 간 데까지의 Runtime과 `runtime_arn`. | 역할과 도구 정책은 Grant가 바꾼 대로입니다. 무엇이 도는지는 Runtime이 어디까지 고쳐졌느냐에 달렸고, 해 보지 않았습니다. |
| Entry, TestCall, Approve | 위의 것과 target, `review_permit_`, `guard_secret_`, Approve가 건 전사 정책. 사용자는 들어오지 못합니다. 예외는 아래의 남은 `entry_permit_`입니다. | 떨어진 버전의 코드가 이전 버전의 `entry_permit_`으로 사용자의 호출을 받습니다. |
| 그다음 `reject.sh`를 돌리면 | 레코드가 `REJECTED`가 되고 위의 것을 모두 지웁니다. | 레코드만 `REJECTED`가 되고 아무것도 지우지 않습니다. |

그 에이전트의 지금 버전을 올린 뒤에 `MODEL_ID`가 바뀌었다면, Grant부터 Deploy가 Runtime을 고치기까지 돌고 있는 버전의 모델 호출은 정책으로 보면 모두 거부됩니다. 새 버전이 그 사이에서 떨어지면 그 상태로 남습니다.

### 승인된 에이전트의 새 버전이 떨어졌을 때 할 일

Read나 Scan에서 떨어졌으면 팀이 고친 버전을 다시 제출합니다. Grant 뒤에서 떨어졌으면 에이전트가 승인되지 않은 도구 정책이나 코드로 사용자의 호출을 받을 수 있으므로, 이 순서로 합니다.

1. `platform_team/agent_stop/stop.sh <에이전트>`로 사용자를 막습니다. 심사의 시험 호출은 막지 않습니다([에이전트 멈추기와 재개](../agent_stop/README.md)).
2. 팀에게 알릴 사유가 있으면 `reject.sh <에이전트> "<사유>"`를 돌립니다. 레코드가 `REJECTED`가 될 뿐 아무것도 지우지 않습니다.
3. 팀이 고친 버전을 다시 제출합니다(`publish.sh`). 새 심사가 도구 정책과 Runtime을 새 신청서에 맞춥니다.
4. 그 심사가 승인되면 `platform_team/agent_stop/resume.sh <에이전트>`로 다시 엽니다. 심사는 멈춤 정책을 지우지 않습니다.

2026-11-22의 운영 확인(`make e2e-ops`)에서 1, 3, 4를 돌려 봤습니다. 그때 멈춘 것은 심사를 지난 버전이었습니다.

### 제출물의 잘못이 아닌 알림

| 알림의 오류 | 뜻과 할 일 |
|---|---|
| Read의 `a review of this record is already running: <실행 이름>` | 앞선 심사가 아직 돌고 있어 이 심사는 아무것도 바꾸지 않고 멈췄습니다. 팀이 그사이에 다시 제출했다면 앞선 심사도 보통 Approve에서 떨어지므로(`the record changed after the review started`), 두 심사가 멈춘 뒤 한 번 더 제출합니다. |
| Approve의 `policy <정책> is <모드>, but /<prefix>/policies/<전사 정책> is <모드>: the approval does not switch modes; rollout.sh … does` | 심사 중에 rollout이 이 에이전트에 전사 정책을 다른 모드로 걸었습니다. 플랫폼팀이 알림이 말하는 `rollout.sh`로 모드를 맞추고 팀이 다시 제출합니다. `… not written by rollout`이면 SSM의 그 값을 고친 뒤 다시 제출합니다. |
| Approve의 `taking back entry_permit_<에이전트>, which this review made, failed too` | Approve가 건 `entry_permit_<에이전트>`가 남아, 승인된 적이 없는 에이전트에 사용자가 들어올 수 있습니다. `stop.sh <에이전트>`로 막습니다. 반려는 이 정책이 있으면 아무것도 지우지 않으므로 `make destroy`가 지웁니다. |

Approve 도중에 Lambda가 끊겨(제한 시간, 메모리 부족) 지우는 코드가 돌지 않았을 때도 `entry_permit_<에이전트>`가 남습니다. 위의 경우는 모두 코드가 그렇게 하고 AWS에서는 해 보지 않았습니다.

## 반려

심사가 떨어진 에이전트는 플랫폼팀이 사유를 적어 반려합니다. 플랫폼팀의 자격 증명으로 돌고, 접두어와 리전은 `.env`에서 읽습니다([시작하기의 `.env`](../../docs/getting-started.md#env)).

```
platform_team/hosting_review/reject.sh <에이전트> "<사유>"
platform_team/hosting_review/reject.sh quality_agent "jinja2 2.11.2 has published advisories"
```

사유는 꼭 적습니다(255자까지). 팀은 레코드에서 사유를 읽고 고친 것을 다시 제출합니다. 하는 일은 레코드의 상태와 `entry_permit_<에이전트>`가 있는지에 따라 다릅니다.

| 레코드의 상태 | `entry_permit_`이 없을 때 | `entry_permit_`이 있을 때 |
|---|---|---|
| `PENDING_APPROVAL` | `REJECTED`로 바꾸고 심사가 남긴 것을 지웁니다. | `REJECTED`로 바꾸기만 하고 아무것도 지우지 않습니다. |
| `REJECTED` | 상태와 사유는 그대로 두고 지우는 일만 다시 합니다. 앞의 반려가 중간에 멈췄거나 심사 중에 레코드가 반려됐을 때 씁니다. | 아무것도 바꾸지 않습니다. |
| `DRAFT` | 상태를 그대로 두고 지웁니다. 심사 중에 팀이 레코드를 고친 경우입니다. | 거부합니다. |
| `APPROVED` | 거부합니다(`approved agents are stopped, not rejected`). | 거부합니다. |

레코드가 없거나 그 밖의 상태여도 거부합니다. 거부하면 아무것도 바꾸지 않습니다.

### 지우는 것과 순서

| 순서 | 무엇 | 이름 |
|---|---|---|
| 1 | 정책 | `entry_permit_<에이전트>`, `review_permit_<에이전트>`, 그 에이전트의 `tool_<에이전트>_<Target>_<도구>` 모두, `guard_secret_<에이전트>`, `guard_prompt_<에이전트>`, `stop_agent_<에이전트>` |
| 2 | 에이전트 게이트웨이의 target | 에이전트 이름의 CamelCase(예: `QualityAgent`) |
| 3 | harness(harness 에이전트만) | `<prefix>_<에이전트>` |
| 4 | Runtime | `<prefix>_<에이전트>` |
| 5 | Runtime의 로그 그룹 | `/aws/bedrock-agentcore/runtimes/<Runtime 이름>-<ID 10자>-<endpoint>` |
| 6 | 코드 패키지 | 제출 버킷의 `packages/<에이전트>/` 아래의 모든 version |
| 7 | 실행 역할 | `<prefix>-agent-<에이전트>-role`. 권한 경계는 그대로 둡니다. |
| 8 | SSM 값 | `/<prefix>/agents/<에이전트>/` 아래 |

- 들여보내는 `entry_permit_`을 먼저, 막는 정책을 나중에 지우므로 멈춘 에이전트가 정리 도중에 열리지 않습니다. 이 순서는 AWS에서 확인하지 않았습니다.
- 이름은 그 에이전트 하나의 것으로만 만들고, 접두어로 넓게 찾아 지우지 않습니다. `quality`를 반려해도 `quality_agent`의 것은 그대로입니다.
- 지우기 전에 역할, Runtime, harness가 허브의 것인지 읽어서 확인합니다(`check_agent`). 역할에 권한 경계 `<prefix>-agent-boundary`가 없거나 Runtime의 실행 역할이 그 에이전트의 것이 아니면, 아무것도 지우지 않고 멈춥니다.
- 없는 것은 이미 지워진 것으로 봅니다. 역할과 SSM 값을 맨 뒤에 지우므로, 중간에 멈춰도 다시 돌리면 이어서 지웁니다.

### 남기는 것

- 제출 버킷의 zip. 무엇이 제출됐는지의 기록이고, bucket은 `terraform destroy`가 지웁니다.
- 카탈로그 레코드. `REJECTED`와 사유가 남습니다. 레코드를 지우는 것은 `make destroy`뿐입니다.

### `make destroy`

`make destroy`는 `terraform destroy` 앞에서 같은 정리를 모든 에이전트에 하고(`python -m platform_team.hosting_review.agent_cleanup`), 승인된 에이전트와 그 레코드도 지웁니다. 에이전트는 카탈로그의 AGENT 레코드, SSM `/<prefix>/agents/` 아래의 값, `<prefix>-agent-<에이전트>-role` 이름의 역할에서 찾습니다.

- 허브의 권한 경계가 없는 역할은 `skipped <역할>: not made by this hub`를 출력하고 건너뜁니다.
- 이 정리가 실패하면 `terraform destroy`를 돌리지 않습니다.
- 마지막에 `--records`가 Registry에 남은 레코드를 종류와 상관없이 모두 지웁니다(`removed record <이름> (<종류>, <상태>)`).
- 전사 정책의 모드는 그 전에 지웁니다([전사 정책의 `make destroy`](../company_policy/README.md#make-destroy)).

### 한계

- 심사가 돌고 있는 동안에는 `reject`가 `a review of record <에이전트> is still running (<실행 이름>): reject after it stops`로 거부합니다. 아직 도는 단계가 지운 것을 다시 만들기 때문입니다.
- 알림이나 Step Functions 콘솔에서 실행이 `FAILED`로 멈춘 것을 확인한 뒤 반려합니다.
- 에이전트 하나만 지우는 명령은 없습니다. 승인된 에이전트는 반려가 거부하고, `make destroy`가 허브 전체와 함께 지웁니다.

## 에이전트 실행 역할의 상한(권한 경계)

Grant는 권한 경계 `<prefix>-agent-boundary`가 달린 역할에만 `CreateRole`과 `PutRolePolicy`를 할 수 있고(`iam:PermissionsBoundary` 조건), 경계를 바꾸거나 떼지 못합니다. 그래서 inline 정책에 무엇이 들어가도 역할은 경계를 넘지 못합니다. `make preload`가 harness 에이전트에 만드는 역할도 같은 함수(`review_steps.ensure_agent_role`)와 같은 경계로 만듭니다.

| 권한 | 경계(상한) | Grant의 inline 정책 |
|---|---|---|
| 모델 호출 | inference profile과 foundation model | 허브의 `MODEL_ID` 하나 |
| workload identity의 토큰 | `workload-identity-directory/default` 아래 | 그 에이전트의 Runtime의 것(`<Runtime 이름>-*`)만 |
| 로그 | `/aws/bedrock-agentcore/runtimes/<prefix>_*`와 `/aws/bedrock-agentcore/runtimes/harness_<prefix>_*` | 그 에이전트의 Runtime의 로그 그룹만 |
| 도구, trace, 메트릭 | 도구 게이트웨이 호출, X-Ray, namespace `bedrock-agentcore`의 메트릭 | 경계와 같습니다. |

- trace와 메트릭의 권한은 AWS 문서의 [Runtime 실행 역할 예시](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html)를 따릅니다. X-Ray의 네 action은 자원 종류가 없어 `"*"`에 주고, `cloudwatch:PutMetricData`는 namespace `bedrock-agentcore`에만 쓰게 합니다.
- 그래서 정책으로 보면 에이전트의 코드는 어떤 서비스 이름으로든 trace를 쓸 수 있고, 그 namespace에 다른 에이전트의 메트릭과 같은 이름으로도 쓸 수 있습니다. 둘 다 해 보지는 않았습니다.
- 로그 그룹 목록 읽기(`logs:DescribeLogGroups`)는 자원으로 좁혀지지 않아 `log-group:*`에 남습니다. 목록을 읽을 뿐 쓰지는 않습니다.
- 그 예시의 `logs:PutResourcePolicy`는 권한을 바꾸는 action이라 넣지 않았습니다. 이 권한 없이 span이 어디에 남았는지는 [모니터링](../agent_monitoring/README.md#에이전트의-trace)에 있습니다.
- 2026-11-23의 실행에서 좁힌 로그 권한으로 거부 줄은 없었고, `stop.sh`가 그 로그 그룹에서 세션을 찾았습니다([세션을 어디서 찾나](../agent_stop/README.md#세션을-어디서-찾나)).
- 토큰의 자원을 좁힌 것은 확인되지 않았습니다. 2026-11-22의 실행에서 CloudTrail에 토큰을 받는 호출이 보이지 않았습니다.
- harness 에이전트 역할의 토큰 권한은 harness의 workload identity(`harness_<prefix>_<에이전트>-<10자>`)와 맞지 않습니다. 2026-11-22의 실행에서 harness는 이 권한 없이 모델과 도구 게이트웨이를 불렀습니다.

## 알려진 한계: 배포 단계의 권한

배포 역할의 정책(`terraform/iam.tf`의 `deploy`)에는 역할, 정책, target을 만들거나 레코드를 승인하는 action이 없습니다.

| 할 수 있는 일 | 범위 |
|---|---|
| Runtime과 그 endpoint 만들기 | `runtime/*`. 이름으로 좁히지 못했습니다. |
| Runtime 고치고 읽기 | 이름이 `<prefix>_`로 시작하는 것 |
| Runtime 목록 읽기(`ListAgentRuntimes`) | 계정의 모든 Runtime |
| 역할 넘기기(`iam:PassRole`) | 이름이 `<prefix>-agent-*-role`인 역할, AgentCore에만 |
| 코드 패키지 쓰기, SSM 값 쓰기 | 제출 버킷의 `packages/` 아래, `/<prefix>/agents/<에이전트>/runtime_arn` |

IAM이 `CreateAgentRuntime`과 `CreateAgentRuntimeEndpoint`의 권한을 `runtime/*`로 확인하므로, 자원으로는 이름을 좁힐 수 없습니다. 2026-11-22에 읽은 AWS의 [Service Authorization Reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_amazonbedrockagentcore.html)에는 Runtime의 이름으로 거르는 조건 키도 없습니다. 그래서 한계가 둘 남습니다.

- 배포 역할 하나가 모든 심사에 쓰입니다. 배포 build 안에서 코드를 실행할 수 있으면 다른 에이전트의 Runtime을 바꾸거나, 실행 역할을 넘기거나, 코드 패키지를 덮어쓰거나, `runtime_arn`을 쓸 수 있습니다.
- 이름이 `<prefix>_`로 시작하지 않는 Runtime도 정책으로는 만들 수 있고, 해 보지는 않았습니다. 그런 Runtime은 허브의 정리(`reject`, `make destroy`)와 `e2e_checks/check_cleanup.py`가 찾지 못합니다.

피해를 줄이는 것은 이렇습니다. Entry는 그 에이전트의 Runtime이 아닌 ARN을 거부합니다. 이미 만든 Runtime 버전은 코드 패키지의 object version을 가리키므로 덮어써도 그대로입니다. 같은 key를 덮어써 보지는 않았습니다. 넘길 수 있는 역할은 이름이 `<prefix>-agent-*-role`인 것이고, Grant는 이 이름의 역할을 경계를 달아서만 만듭니다. 허브 밖에서 이 이름으로 만든 역할에는 경계가 없을 수 있지만, 그런 역할을 만들 IAM 권한은 심사의 어느 역할에도 없습니다. 다만 다른 에이전트의 역할로 도는 Runtime은 그 에이전트에게 허락된 도구를 부를 수 있습니다.

지금 배포 build를 지키는 것은 제출된 파일이 그 안에서 실행되지 않게 하는 장치입니다. 위의 "제출 버킷과 배포 build"에 적은 것에 더해, 제출된 `.py` 파일은 build 안에서 import되거나 실행되지 않습니다. `uv.toml`을 심은 제출물은 지금의 배포 build로 AWS에서 돌려 보지 않았습니다. 운영 환경이라면 심사마다 세션 정책으로 좁힌 자격 증명을 build에 넘겨, 그 에이전트의 Runtime과 실행 역할에만 닿게 합니다. 이 방법은 여기서 확인하지 않았습니다.

## 알려진 한계: 시험 호출

TestCall은 HTTP 상태만 봅니다. 보통 질문(`What is the spec of part P-100?`)에 200이 오고 예시 access key가 든 질문이 403이면 통과입니다. 답의 내용은 보지 않으므로 에이전트가 제대로 일하는지는 알 수 없습니다. 2026-11-22의 실행에서 `release_review`는 이 질문에 `ERROR: unexpected model answer: ...`를 200으로 돌려줬고 심사를 통과했습니다.

## 파일

모두 이 폴더에 있습니다. Lambda 단계 다섯은 `review_steps.py`, 검사 단계는 `buildspec_scan.yml`과 `submission_check.py`, 배포 단계는 `buildspec_deploy.yml`과 `deploy_build.py`입니다. 반려는 `reject.sh`와 `reject_agent.py`, 정리는 `agent_cleanup.py`, `make preload`는 `preload_agents.py`이고, 기반 자원과 단계마다의 역할은 `terraform/`에 있습니다.
