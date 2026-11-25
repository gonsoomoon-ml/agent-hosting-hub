# AI 에이전트 호스팅 허브

한국어 | [English](README.en.md) | [시연 영상 (YouTube)](https://youtu.be/cp0YKgAmrxM)

Amazon Bedrock AgentCore 위에서 여러 개발팀의 AI 에이전트를 한곳에 올리고 관리하는 허브를 만듭니다.
플랫폼팀은 허브(게이트웨이, 정책, 카탈로그)를 만들고, 개발팀은 에이전트를 만들어 허브에 올립니다.
정책은 Cedar로 쓰고, 어떤 에이전트가 어떤 도구를 쓸 수 있는지 허브가 정합니다.

> 들어 있는 것은 두 흐름입니다. 흐름 1은 호스팅(신청, 심사, 승인, 반려와 재신청)이고, 흐름 2는 운영(전사 정책의 기록 모드와 적용, 커스텀 가드레일, 승인된 에이전트의 새 버전, 도구 호출 경보(CloudWatch alarm), 에이전트 하나의 멈춤과 재개, 사용량 보고, 미리 올려 둔 에이전트 둘)입니다. 두 흐름 모두 실제 AWS에서 처음부터 끝까지 확인하는 스크립트가 있습니다(`make e2e`, `make e2e-ops`).

[![개념도: 흐름 1(호스팅)과 흐름 2(운영)](docs/hosting-hub-concept.png)](docs/hosting-hub-concept.png)

개념도는 두 흐름을 상자와 번호 붙은 화살표로 그린 것입니다. 흐름 1(호스팅)은 ①부터 ⑥까지이고, 흐름 2(운영)는 ⑦부터 ⑫까지입니다.

[![구성도: 같은 두 흐름을 AWS 서비스 이름으로 그린 그림](docs/hosting-hub-system.png)](docs/hosting-hub-system.png)

구성도는 개념도와 같은 자리에 AWS 서비스의 이름을 넣은 것입니다. 예를 들어 ⑤는 개념도에서 "에이전트 배포"이고 구성도에서 `CreateAgentRuntime`입니다. 폴더별 설명은 [구조와 코드](docs/architecture.md)에 있습니다.

## 영상

[![허브의 시연 영상의 한 장면: release_review 에이전트의 호스팅 심사가 일곱 단계를 지나는 화면](demo_video/poster.png)](https://youtu.be/cp0YKgAmrxM)

해설이 든 전체 영상(15분 16초, 한국어 해설과 자막)은 YouTube에서 볼 수 있습니다: <https://youtu.be/cp0YKgAmrxM>. 위의 그림을 눌러도 열립니다.

- 준비: 허브 화면의 홈입니다.
- 1단계: 개발자 PC의 Claude Code가 카탈로그의 MCP 서버에서 공유 도구를 찾고 표준 템플릿으로 `quality_agent` 에이전트의 파일을 만듭니다(실행하거나 올리지는 않습니다). 개발자는 에이전트 둘의 호스팅을 신청합니다. `release_review`와, 심사가 걸러 내는 것을 보이려고 취약한 패키지를 일부러 넣은 `quality_agent`입니다.
- 2단계: 두 신청의 호스팅 심사가 자동으로 돌아 `quality_agent` 에이전트는 의존성 검사(Scan)에서 멈추고 `release_review` 에이전트는 일곱 단계를 지나 승인되어 답하며, 플랫폼팀이 사유를 적어 반려하고 고친 버전이 승인됩니다.
- 3단계: 전사 정책 `guard_prompt`를 기록 모드로 걸고, 에이전트에게 내리는 지시가 든 요청이 막히지 않은 채 집계에 한 건 잡힙니다.
- 4단계: 적용 모드로 올리면 같은 요청이 `release_review` 에이전트와 `docs_adk` 에이전트 모두 403이고, 커스텀 가드레일을 붙이기 전과 뒤에 코드명이 든 요청과 사번이 든 답이 어떻게 다른지 보입니다.
- 5단계: 사고를 보이려고 도구를 횟수 제한 없이 다시 부르게 만든 `quality_agent`의 새 버전이 심사를 통과합니다. 사용자의 질문에 답하지 못한 채 도구만 반복해 부르고, 도구 호출 경보가 울립니다. 플랫폼팀이 그 에이전트 하나만 멈추고, 다른 에이전트는 그대로 답합니다. Claude Code가 로그와 코드를 읽어 원인을 찾고, 고친 버전이 멈춘 채로 승인되고, 재개하면 다시 답합니다.

영상 파일은 이 저장소에 없습니다. 영상을 만드는 방법은 [`demo_video/README.md`](demo_video/README.md)에 있습니다.

## 빠른 시작

준비물은 Terraform 1.9 이상, Python 3.12 이상과 uv, AWS 자격 증명, 리전 `us-west-2`, Amazon Bedrock 모델 사용 권한입니다. 자세한 것은 [시작하기](docs/getting-started.md)에 있습니다.

```bash
cp .env.example .env   # 허브의 세 값: 리전, 접두어, 모델
make deploy            # 허브의 기반 자원을 배포합니다. 빈 계정에서 4분쯤
make seed              # 공유 도구 레코드를 카탈로그에 넣고 승인합니다. 6초
make preload           # 에이전트 둘을 미리 올려 둡니다. 11분쯤
make ui                # 허브 화면(샘플)을 이 PC에서 실행합니다. http://127.0.0.1:8300
make destroy           # 허브가 만든 것을 모두 지웁니다. 에이전트 수에 따라 9~18분
```

- **요금**: 허브는 켜 두는 서버가 없고, 대부분은 쓰는 만큼(호출 수, 실행 시간, 저장량) 요금이 붙습니다. 다 쓰면 `make destroy`로 지웁니다. [요금과 지우기](docs/cost-and-cleanup.md)
- **영상처럼 해 보기**: 시연 영상의 순서대로 자기 계정에서 직접 해 보려면 [영상처럼 따라 하기](docs/demo-guide.md)를 봅니다.
- **확인**: 두 흐름을 처음부터 끝까지 확인하려면 `make e2e`와 `make e2e-ops`를 돌립니다. [확인한 것](docs/checks.md)

## 무엇이 들어 있나

폴더는 쓰는 사람에 따라 나뉩니다. 아래는 폴더를 두 층까지 펼친 구조입니다. 폴더마다의 설명과 각 README로 가는 링크는 [구조와 코드](docs/architecture.md)에 있습니다.

```text
agent-hosting-hub/
├── Makefile              # make deploy, seed, preload, e2e, e2e-ops, destroy 등(docs/getting-started.md의 "일곱 명령")
├── .env.example          # 허브의 세 값: 리전, 접두어, 모델
│
├── platform_team/        # 플랫폼팀: 허브의 기반 자원과 운영 명령. 기능 하나가 폴더 하나입니다
│   ├── terraform/        #   루트 모듈. 기능 폴더의 terraform/을 묶어 한 번에 올립니다
│   ├── shared_code/      #   여러 기능이 같이 쓰는 코드(설정, AWS 호출, 코드 패키지)
│   ├── agent_catalog/    #   카탈로그(AWS Agent Registry): 신청, 검색, 공유 도구 등록
│   ├── hosting_review/   #   호스팅 심사(Step Functions, Lambda, CodeBuild)와 반려
│   ├── agent_gateway/    #   에이전트 게이트웨이와 에이전트를 부르는 명령
│   ├── tool_gateway/     #   도구 게이트웨이
│   ├── sample_tools/     #   샘플 사내 도구(합성 데이터)
│   ├── company_policy/   #   전사 정책: Cedar 템플릿, 정책 엔진, rollout.sh
│   ├── custom_guardrail/ #   커스텀 가드레일: interceptor Lambda, guardrail.sh
│   ├── agent_monitoring/ #   알림, 도구 호출 경보, 사용량 보고(usage.sh), 로그 읽기
│   ├── agent_stop/       #   에이전트 하나 멈추기와 재개(stop.sh, resume.sh)
│   ├── dev_access/       #   개발팀 역할
│   └── hub_ui/           #   허브 화면(샘플, 이 PC에서만)
│
├── dev_team/             # 개발팀: 템플릿과 예시 에이전트
│   ├── agent_template/   #   표준 템플릿과 올리는 명령(publish.sh)
│   ├── release_review/   #   예시 에이전트(LangGraph)
│   ├── quality_agent/    #   예시 에이전트(Strands). variants/에 데모를 위한 버전 둘
│   └── preloaded_agents/ #   미리 올려 둔 에이전트 둘(docs_adk, spec_assistant)
│
├── docs/                 # 그림 둘과 자세한 문서(아래 "더 읽기")
├── e2e_checks/           # 실제 AWS에서 돌리는 확인 스크립트. spikes/는 가정을 확인한 기록
├── tests/                # 단위 테스트. AWS를 부르지 않습니다
├── demo_scenes/          # 시연 영상의 터미널에서 치는 명령 넷(ask, publish, search, logs)
└── demo_video/           # 시연 영상을 만드는 것: 스토리보드, 녹화 스크립트, 자막과 컷(build.py), 개발자 PC
```

## 더 읽기

| 문서 | 내용 |
|---|---|
| [시작하기](docs/getting-started.md) | 사전 요건, `.env`, 일곱 명령과 걸린 시간, 미리 올려 둔 에이전트 둘 |
| [명령 모음](docs/commands.md) | 운영의 명령, 허브 화면(샘플), 영상에서 치는 명령 |
| [확인한 것](docs/checks.md) | `make e2e`와 `make e2e-ops`가 확인하는 것, 실행한 날짜와 본 것 |
| [요금과 지우기](docs/cost-and-cleanup.md) | 요금이 드는 자원, `make destroy`가 지우는 것과 남기는 것 |
| [알려진 한계](docs/limits.md) | 이 샘플의 한계 |
| [구조와 코드](docs/architecture.md) | 그림 둘, 폴더별 설명, 코드 따라 읽기 |
| [영상처럼 따라 하기](docs/demo-guide.md) | 시연 영상의 순서를 자기 계정에서 손으로 따라 하는 안내 |
| [영상을 만드는 것](demo_video/README.md) | 스토리보드, 녹화, 자막과 컷, 개발자 PC |
| [영상에서 치는 명령](demo_scenes/README.md) | `ask`, `publish`, `search`, `logs`와 장면의 순서 |
| [줄이기 전의 문서](https://github.com/gonsoomoon-ml/agent-hosting-hub/tree/docs-detailed-2026-11-25) | 실행마다 잰 시간과 본 것을 모두 적은 이전 버전입니다(태그 `docs-detailed-2026-11-25`). 지금의 문서는 2026-11-25에 줄였습니다 |
