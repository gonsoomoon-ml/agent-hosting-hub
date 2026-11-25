# 전사 정책

허브의 모든 정책이 들어가는 policy engine 하나(`<prefix>_pe`)를 만듭니다. 두 게이트웨이가 이 engine을 함께 쓰고 `ENFORCE`로 따릅니다. 정책은 Cedar로 씁니다. 개발팀의 공유 도구 permit, 호스팅 심사가 주는 permit, 플랫폼팀이 거는 전사 정책이 모두 여기에 있습니다.

## 개념도에서의 위치

[개념도](../../docs/hosting-hub-concept.png)의 ⑫ "전사 정책 설정, 이상 에이전트 차단"입니다. ④ "에이전트에 도구 권한 부여"와 ⑥의 6a "요청 허용"의 permit도 이 engine에 들어갑니다.

## 정책이 요청을 판정하는 방법

게이트웨이는 요청을 받을 때마다 policy engine에 묻고, 그 결정대로 요청을 넘기거나 403으로 막습니다. Cedar의 규칙대로 맞는 `permit`이 없으면 거부하고, `forbid`가 하나라도 맞으면 `permit`이 있어도 거부합니다.

```
호출자 (IAM 역할로 서명된 요청)
  │  "quality_agent에 이 질문을 보냅니다"
  ▼
에이전트 게이트웨이 <prefix>-agents
  │  policy engine에 묻습니다
  ▼
policy engine <prefix>_pe
  │  요청을 네 가지로 봅니다
  │    principal  누가       arn:aws:sts::<account>:assumed-role/<역할>
  │    action     무엇을     QualityAgent___POST:/invocations
  │    resource   어디서     이 게이트웨이의 ARN
  │    context    내용       질문(prompt)
  │
  │  이 요청에 맞는 정책을 모두 찾습니다
  │    permit 맞음? ──아니요──▶ 거부 (기본 거부)
  │       │ 예
  │    forbid 맞음? ───예────▶ 거부 (forbid가 이깁니다)
  │       │ 아니요
  ▼       ▼
허용 → 에이전트(Runtime)로 넘깁니다
```

같은 에이전트라도 걸린 정책에 따라 결정이 다릅니다. 정책의 이름과 거는 단계는 [호스팅 심사의 정책 이름](../hosting_review/README.md#정책-이름)에 있고, Cedar 문장은 `policy_templates/`에 있습니다.

```
상황                          맞는 permit       맞는 forbid     결과
심사 중, 사용자가 부름          없음              -              거부 (기본 거부)
심사 중, TestCall이 부름        review_permit     -              허용
승인 뒤, 보통 질문              entry_permit      -              허용
승인 뒤, access key가 든 질문   entry_permit      guard_secret   거부
멈춘 뒤, 사용자가 부름          entry_permit      stop_agent     거부
멈춘 뒤, TestCall이 부름        두 permit         없음           허용 (unless로 빠집니다)
```

permit을 더하면 문이 열리고, forbid를 더하면 다른 정책을 지우지 않아도 막힙니다. 멈추기와 재개는 forbid 하나를 걸고 지우는 일입니다. 도구 게이트웨이도 같은 engine으로 판정하고, 그 에이전트의 실행 역할에 준 `tool_<에이전트>_<Target>_<도구>` permit이 없는 도구는 부를 수 없습니다.

## 전사 정책 켜고 끄기

전사 정책은 플랫폼팀이 에이전트 게이트웨이에 진입 target이 있는 모든 에이전트에 하나씩 거는 정책입니다. 지금은 `guard_prompt` 하나입니다. 프롬프트 공격(`PROMPT_INJECTION`, 신뢰도 0.4 초과)인 질문을 에이전트 게이트웨이에서 거부하고, 에이전트마다 이름은 `guard_prompt_<에이전트>`입니다.

먼저 기록 모드로 켜서 무엇에 맞는지 보고, 그다음 적용 모드로 올립니다.

```
platform_team/company_policy/rollout.sh guard_prompt log-only   # 켭니다: 모든 에이전트에 기록 모드로
platform_team/company_policy/rollout.sh guard_prompt active     # 올립니다: 결정을 요청에 반영합니다
platform_team/company_policy/rollout.sh guard_prompt off        # 끕니다: 모든 에이전트에서 지웁니다
platform_team/company_policy/rollout.sh guard_prompt report     # 에이전트마다 지난 60분의 기록을 읽습니다
```

| 낱말 | 하는 일 |
|---|---|
| `log-only` | 기록 모드(`LOG_ONLY`)로 켭니다. 정책은 요청을 막지 않고, 맞은 요청을 메트릭에 남깁니다. |
| `active` | 적용 모드(`ACTIVE`)로 올립니다. 정책의 결정이 요청에 반영됩니다. |
| `off` | SSM의 값을 지우고, 이 정책을 가진 모든 에이전트에서 정책을 지웁니다. 다른 종류의 정책은 그대로입니다. |
| `report` | 에이전트마다 적용 모드와, 지난 60분의 CloudWatch 메트릭 `LogOnlyMatches`, `LogOnlyDecisionFlips`의 합을 출력합니다. |

- 정책에는 값이 둘 있고, 둘 다 `ACTIVE`라는 낱말을 쓰지만 뜻이 다릅니다. 상태(`status`)가 `ACTIVE`이면 정책이 다 만들어진 것이고, 적용 모드(`enforcementMode`)가 `ACTIVE`이면 정책의 결정이 요청에 반영됩니다.
- 플랫폼팀의 자격 증명으로 돌고, 허브의 접두어와 리전은 `.env`에서 읽습니다([시작하기의 `.env`](../../docs/getting-started.md#env)). 모르는 정책이나 낱말이면 사용법을 출력하고 아무것도 바꾸지 않습니다.
- `log-only`와 `active`는 모드를 SSM `/<prefix>/policies/<정책>`에 먼저 적습니다. 그다음 에이전트마다 정책을 그 모드로 만들거나, 있는 정책의 모드만 바꿉니다(`UpdatePolicy`).
- 에이전트마다 `created`, `switched`, `unchanged`, `failed (<이유>)` 가운데 한 줄을 출력합니다. 한 에이전트가 실패해도 나머지는 계속합니다.
- 끝에 정책 목록을 다시 읽어 에이전트마다 읽힌 모드를 출력합니다(`<에이전트>: reads LOG_ONLY`). 실패했거나 다른 모드로 읽힌 에이전트가 있으면 0이 아닌 값으로 끝나므로, 같은 명령을 다시 돌립니다.
- 메트릭은 정책의 ID로 셉니다. 정책을 지우고 다시 만들면 0부터 셉니다.

### AWS에서 본 것

2026-11-22에 `make e2e-ops`가 에이전트 둘이나 셋인 허브에서 이 명령들을 돌렸습니다.

- `log-only`는 27초, `active`는 35초, `off`는 27초 걸렸습니다.
- 숨은 지시가 든 요청은 기록 모드에서 200, `active` 뒤에 403, `off` 뒤에 다시 200이었습니다. 적용 모드인 동안 승인된 `docs_adk`에서도 403이었습니다.
- `report`는 기록 모드에서 보낸 그 요청을 3초 뒤에는 0, 65초 뒤에는 1로 셌습니다.

### 새로 승인되는 에이전트

호스팅 심사의 Approve 단계는 `entry_permit_<에이전트>`를 걸기 전에, SSM `/<prefix>/policies/`에 적힌 전사 정책을 그 모드 그대로 새 에이전트에 겁니다.

같은 이름의 정책이 다른 모드로 있거나, SSM에 모르는 정책이나 모드가 있으면 Approve는 실패합니다. 승인 없이 알림으로 빠지고, 그 뒤에 할 일은 [호스팅 심사, 제출물의 잘못이 아닌 알림](../hosting_review/README.md#제출물의-잘못이-아닌-알림)에 있습니다.

### `make destroy`

`make destroy`는 에이전트를 정리하기 전에 SSM `/<prefix>/policies/` 아래의 값을 지웁니다(`python -m platform_team.company_policy.policy_rollout --forget`). 이 값은 Terraform 밖에 있어 `terraform destroy`가 지우지 않습니다. 정책 자체는 그다음의 에이전트 정리가 지웁니다. 값이 남은 채로 지우는 것은 해 보지 않았습니다.

## 한계

- harness 에이전트에는 진입 target이 없어 전사 정책이 걸리지 않습니다.
- `off`와 승인이 겹치면 새 에이전트에 정책이 남을 수 있습니다. 그때는 `off`를 한 번 더 돌립니다.
- AWS에서 해 보지 않은 것: rollout과 승인이 겹치는 것, 한 에이전트에서만 실패하는 rollout, SSM에 모르는 값이 있을 때의 Approve.

## 파일

| 파일 | 역할 |
|---|---|
| `terraform/` | policy engine `<prefix>_pe`. 내보내는 값은 `policy_engine_id`, `policy_engine_arn`. |
| `policy_templates/` | Cedar 문장의 템플릿. Python과 Terraform이 같은 파일을 읽습니다. |
| `cedar_statements.py` | 템플릿에 값을 채워 Cedar 문장을 만듭니다. 값이 비었거나 따옴표, 역슬래시, 줄바꿈이 들어 있으면 오류를 냅니다. |
| `policy_names.py` | 에이전트마다 만드는 정책의 이름과 그 한도(48자). |
| `policy_engine.py` | 정책을 만들고, 지우고, 목록을 읽습니다. |
| `policy_rollout.py` | 전사 정책의 목록, 켜기와 모드 맞추기, 끄기, 새 에이전트에 걸기, 메트릭 읽기, SSM 값 지우기. |
| `rollout.sh` | 위의 명령 넷. |
