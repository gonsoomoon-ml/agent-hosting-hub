# 데모 장면의 명령

시연 영상의 터미널 장면에서 사람이 치는 명령 넷이다. 각각 짧은 셸 파일이고, 허브의 환경 값(접두어, 리전, 모델)을 `platform_team/shared_code/hub_env.sh`로 읽은 다음 Python 모듈 하나를 부른다. 파일의 위치에서 저장소의 루트를 찾으므로 어느 폴더에서 쳐도 된다. 첫 줄에 부르는 명령을 한 줄(100칸 이내)로 찍고, 그다음에 결과를 찍는다. 기대한 실패(403, 없는 에이전트, 로그 그룹 없음)는 Python 오류 출력 없이 한 줄로 말한다. 찍는 글에서 계정 ID는 `<ACCOUNT>`로 가린다.

2026-11-23 현재 이 명령들은 단위 시험(`tests/test_ask_agent.py`, `test_search_catalog.py`, `test_agent_logs.py`, `test_demo_scenes.py`)으로만 확인했고, AWS에서는 돌려 보지 않았다. 아래 "프롬프트" 열은 `make e2e`와 `make e2e-ops`가 2026-11-22와 2026-11-23의 실행에서 쓴 문장이고, 이 명령으로 보낸 것은 아니다.

## 명령

| 명령 | 누가 치나 | 하는 일 | 성공하면 | 거절하면 |
|---|---|---|---|---|
| `demo_scenes/ask <에이전트> "<프롬프트>"` 또는 `--file <경로>` (`--timeout <초>`, `--session <ID>`) | 사용자(에이전트 게이트웨이를 부를 수 있는 IAM 주체) | 에이전트 게이트웨이로 에이전트를 부른다 | 첫 줄 `HTTP 200 (<초> s)`, 그다음 줄부터 답. 종료 값 0 | 첫 줄 `HTTP 403 (<초> s)`, 그다음 줄에 게이트웨이의 문장(`error` 또는 `message`). 종료 값 1. 에이전트 이름이 신청서의 규칙에 맞지 않으면 아무것도 부르지 않고 한 줄로 이유를 말하고 종료 값 2. 시간 안에 답이 없으면 한 줄(`no answer from <에이전트> within <초> s`)과 종료 값 1 |
| `demo_scenes/publish <에이전트> [변형]` | 개발자 | `dev_team/<에이전트>`의 코드를 올리고, 신청서를 카탈로그에 쓰고, 승인을 요청한다(호스팅 심사가 시작된다) | `platform_team/agent_catalog/publish_agent.py`가 찍는 줄(올린 곳, record, 상태) | 없는 에이전트나 없는 변형이면 있는 것의 목록을 한 줄로 말하고 종료 값 2. 올리기에 실패하면 `publish_agent.py`의 한 줄 |
| `demo_scenes/search "<검색어>"` | 개발자 | 카탈로그를 검색한다. 승인된 record만 나온다 | record마다 `이름  (종류)`, 설명, 도구라면 `tool <이름>: <입력 필드>` | 맞는 것이 없으면 `no approved record matches "<검색어>"`(종료 값 0). 검색을 못 하면 한 줄과 종료 값 1 |
| `demo_scenes/logs <에이전트> [분]` | 개발자 | 에이전트의 Runtime 로그 그룹에서 가장 새 줄 200개까지를 오래된 줄부터 보인다(분은 15가 기본) | 첫 줄 `<에이전트>: the newest <n> log lines of the last <분> minutes`, 그다음 줄부터 로그 | 로그 그룹이 없으면 `no log group for <에이전트> ...` 한 줄과 종료 값 1. 그 시간에 줄이 없으면 한 줄과 종료 값 0 |

- `publish`의 변형은 `dev_team/<에이전트>/variants/` 아래의 폴더다. 지금 있는 것은 `quality_agent`의 `v1-vulnerable`(취약한 라이브러리)과 `v2-loop`(도구를 되풀이해 부르는 판)이다.
- `logs`는 `runtime-logs-<세션 ID>` 스트림의 줄만 읽는다. `otel-rt-logs`(2026-11-22에 같은 줄의 복사본이 있었다)와 `spans`, `build-logs-*`는 읽지 않는다. 쓰는 호출은 `DescribeLogGroups`와 `FilterLogEvents`뿐이라 SSM을 읽지 않는다. 개발자 역할이 그 로그 그룹을 읽을 수 있어야 돌아간다(지금의 `platform_team/dev_access`의 역할에는 그 권한이 없다).
- `search`와 `ask`는 허브가 SSM `/<접두어>/platform`에 적어 둔 값(카탈로그 ID, 게이트웨이 ID)을 읽는다. `search`가 record의 도구 입력 필드를 보이는 것은 검색 결과나 `GetRegistryRecord`가 record의 custom descriptor를 주는 경우다. 코드가 그렇게 하고, AWS에서는 돌려 보지 않았다.

## 입력 파일

- `demo_scenes/inputs/change-ok.txt`: `release_review`에게 보내는 변경 설명. 규칙을 모두 지킨다(`make e2e`의 같은 문장은 2026-11-23의 실행에서 200과 `OK`를 받았다).
- `demo_scenes/inputs/change-with-hidden-instruction.txt`: 같은 변경 설명에 주석 한 줄을 덧붙였다. 그 주석이 `make e2e-ops`가 `HIDDEN`으로 쓰는 문장(앞선 지시를 무시하라는 문장)이다.

## 장면의 순서

각 장면의 명령, 프롬프트, 장면이 필요로 하는 상태와 남기는 상태다. 허브가 올라와 있고(`make deploy`, `make seed`, `make preload`가 끝나 있다) 개발자 컨테이너나 사용자 셸에 각자의 자격 증명이 있다고 본다.

| 장면 | 명령 | 필요한 상태 | 남기는 상태 |
|---|---|---|---|
| 호스팅 신청 | `demo_scenes/publish quality_agent v1-vulnerable`, `demo_scenes/publish release_review` | 두 에이전트가 아직 없다 | 두 record가 승인 대기이고 호스팅 심사 둘이 돈다 |
| 호스팅된 에이전트를 부른다 | `demo_scenes/ask release_review --file demo_scenes/inputs/change-ok.txt` | `release_review`가 승인되어 호스팅 중이다 | 없다 |
| 취약한 판을 고쳐 다시 신청한다 | `demo_scenes/publish quality_agent` | `quality_agent`의 취약한 판이 반려되어 있다 | 새 판의 심사가 돈다 |
| 승인된 에이전트가 답한다 | `demo_scenes/ask quality_agent "What is the spec of part P-100?"` | `quality_agent`가 승인되어 있다 | 없다 |
| 전사 정책이 숨은 지시를 막는다(기록 모드에서는 지나고, 적용 모드에서는 막는다) | `demo_scenes/ask release_review --file demo_scenes/inputs/change-with-hidden-instruction.txt`(기록 모드일 때와 적용 모드일 때), 같은 파일로 `docs_adk`도 | 전사 정책 `guard_prompt`가 해당 모드이다 | 없다 |
| 커스텀 가드레일 전과 후 | 전: `demo_scenes/ask quality_agent "Summarise the schedule of Project Falcon for part P-100."`, 후: 같은 명령과 `demo_scenes/ask quality_agent "What was the result of inspection Q-1001, and what is the specification of the part it inspected?"` | 후에는 커스텀 가드레일이 붙어 있다 | 없다 |
| 사고(도구를 되풀이해 부르는 판) | `demo_scenes/publish quality_agent v2-loop`, 심사가 끝난 뒤 `demo_scenes/ask quality_agent "What is the result of inspection Q-1002?" --timeout 60` | `quality_agent`의 한 판이 승인되어 있다 | 그 에이전트가 되풀이 호출을 계속한다. 도구 호출 경보가 울린다. `--timeout 60`은 AWS에서 해 보지 않았다(`make e2e-ops`는 20초에 포기했다) |
| 이웃은 영향이 없다 | `demo_scenes/ask quality_agent "What is the spec of part P-100?"`, `demo_scenes/ask release_review --file demo_scenes/inputs/change-ok.txt`, `demo_scenes/ask docs_adk "What is our standard for versioning an API?"` | `quality_agent`를 멈춘 상태다 | 없다. `quality_agent`는 403, 나머지는 200이다 |
| 원인을 로그에서 본다 | `demo_scenes/logs quality_agent` | 사고의 판이 돌았다 | 없다. 되풀이하는 줄은 `asking again (<n>)`이고 분당 23~25줄이었다(2026-11-23) |
| 고친 판으로 돌아온다 | `demo_scenes/publish quality_agent`, 승인된 뒤 `demo_scenes/ask quality_agent "What was the result of inspection Q-1001, and what is the specification of the part it inspected?"` | 에이전트가 멈춰 있고 고친 판을 올린다. 재개한 뒤에 부른다 | 고친 판이 승인되어 돈다 |

카탈로그 검색은 `demo_scenes/search "inspection results and part specifications"`가 `make e2e-ops`의 검색어이고(2026-11-23에 다섯 record를 돌려주었다), `demo_scenes/search "part specification tool"`과 `demo_scenes/search "release rules review request"`가 `make e2e`의 검색어다. 이 명령으로 낸 결과는 AWS에서 해 보지 않았다.

위 표에서 `P-100`의 규격을 묻는 문장은 이 장면에 맞게 고른 것이다. 같은 문장을 `quality_agent`에게 보내 200을 받은 것은 2026-11-23의 `make e2e-ops` 첫 확인이고, 이 명령으로 보낸 것은 아니다.
