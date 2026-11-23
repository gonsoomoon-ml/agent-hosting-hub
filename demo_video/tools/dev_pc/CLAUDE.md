# 이 폴더에서 일하는 법

AI 에이전트 호스팅 허브에 에이전트를 올리는 개발팀의 작업 폴더다. 셸의 AWS 자격 증명은 허브의 개발팀 역할이다.

## 새 에이전트 만들기

- 템플릿은 `dev_team/agent_template/`이고, 무엇을 쓰고 무엇을 고치지 않는지는 그 폴더의 `README.md`에 있다.
- 새 에이전트는 `dev_team/<에이전트 이름>/`에 둔다. 템플릿의 `main.py`, `hub_tools.py`, `agent.json`, `requirements.txt`를 가져오고, `agent.py`에 `run(prompt) -> (answer, tools_used)`를 쓴다. `main.py`와 `hub_tools.py`는 고치지 않는다.
- `agent.json`에는 이름(소문자와 숫자의 마디를 밑줄 하나로 이은 3~31자), 팀, 프레임워크, 쓸 도구의 목록을 적는다. 도구는 카탈로그에 있는 `<Target>___<tool>` 이름이다.
- `requirements.txt`에는 패키지 이름과 `==`로 고정한 버전만 적는다. 템플릿에 있는 줄은 지우지 않는다.
- 허브의 도구는 `hub_tools.call_tool("<Target>___<tool>", {...})`로 부른다.
- 예시 에이전트는 `dev_team/release_review/`에 있다.

## 카탈로그 검색

허브에서 쓸 수 있는 도구와 에이전트는 카탈로그에 있고, 승인된 것만 검색된다. MCP 서버 `hub-catalog`의 검색 도구로 찾거나, 셸에서 `search "<검색어>"`를 친다.

## 올리기

`publish <에이전트>`가 `dev_team/<에이전트>/`의 코드를 올리고, 신청서를 카탈로그에 쓰고, 승인을 요청한다. 그러면 허브의 호스팅 심사가 시작한다. 올리는 것은 개발자가 직접 친다.

## 로그 보기

`logs <에이전트> [분]`이 그 에이전트의 Runtime 로그에서 최근 줄을 보인다(분을 주지 않으면 15분).

셸 명령 `search`, `publish`, `logs`는 이 폴더의 `demo_scenes/`에 있고 PATH에 들어 있다.

## 고치는 곳

파일은 `dev_team/` 아래에만 쓴다. `demo_scenes/`, `platform_team/`, `pyproject.toml`, `uv.lock`, `.claude/`, `.mcp.json`은 고치지 않는다(설정이 막는다). `dev_team/` 아래에도 `.claude/` 폴더, `.mcp.json`, `CLAUDE.md`는 만들지 않는다(설정이 막는다).
