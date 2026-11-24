# 시연 영상

허브의 시연 영상을 만드는 데 쓰는 것을 모은 폴더다. 영상의 결과물과 녹화의 원본, 개발자 PC의 홈과 자격 증명 파일은 `out/` 아래에 생기고 git에 올라가지 않는다(`.gitignore`).

녹화와 편집은 영상 플러그인 [demo-video](https://github.com/gonsoomoon-ml/claude-extensions/tree/main/plugins/demo-video)의 스크립트(`record_demo.mjs`, `term.mjs`, `edit_demo.py`, `make_cards.py`, 해설이 든 영상의 검사에는 `check_demo.py`)로 한다. `check_demo.py`와 해설이 든 영상에 쓰는 기능은 demo-video 1.4.0부터 있고, 1.4.0은 2026-11-24 현재 아직 공개되지 않았다(위 링크의 `main`은 1.3.0이다). 이 폴더의 스크립트는 그 플러그인의 `scripts` 폴더를 환경 변수 `DEMO_VIDEO_PLUGIN`으로 찾고, 없으면 그렇게 말하고 멈춘다.

## 영상 한 벌 (`scripts/build.py`)

영상의 글은 모두 이 파일 하나에 언어별로 있다. 장면마다 조각이 하나 이상 있고, 조각은 녹화 원본(`out/raw/<장면>.webm`)의 한 구간(카메라 기록의 초)을 한 속도로 자른 것과 그 위의 자막이다. 그리고 카드(처음, 장마다, 비교, 정리, 마무리)와 릴 여섯(`hosting-hub-main-ko.mp4`, `hosting-hub-stage-<1..5>-ko.mp4`)이 있다. 단계마다의 릴은 전체 릴에서 그 단계의 부분과 같고, 1단계의 릴은 준비(허브 화면의 홈)로 시작한다.

```
python3 demo_video/scripts/build.py --check     # 플러그인의 스크립트 파일을 쓰고 글만 검사한다. 릴마다 길이를 찍는다
python3 demo_video/scripts/build.py             # 그다음 클립, 카드, 릴을 만든다 (make_cards.py에 Pillow가 필요하다)
```

무엇을 쓰기 전에 모든 글을 플러그인의 자막 규칙으로 검사하고, 어긋난 글이 하나라도 있으면 글마다 한 줄로 말하고 멈춘다(종료 값 2). 규칙은 이렇다. 45자 이하, em dash, 가운뎃점, 화살표(U+2014, U+00B7, U+2192)를 쓰지 않는다, 속도 표시나 녹화에 대한 말을 쓰지 않는다. 자막, 장의 제목, 카드의 줄은 합니다체 한 문장이다(`니다`로 끝난다). 자막은 카메라 기록(`out/raw/<장면>.camlog.json`)의 샷이나 메모에 걸고, 초로 걸지 않는다. 단계마다 자막 수의 한도(준비 5, 1단계 11, 2단계 12, 3단계 8, 4단계 10, 5단계 18)를 넘지 않는다. 릴은 이 파일이 정한 장면과 카드만 쓴다. 자막과 카드에 두 빌드(소리 없는 것과 해설이 든 것)가 읽지 않는 키가 있으면(철자가 틀린 `ends_early` 같은) 그 자막이나 카드와 키를 한 줄로 말하고 멈춘다. `--check` 없이 돌리면 자르기 전에 카메라 기록을 읽어, 자막마다 그 샷이나 메모가 기록에 있는지, 그 시각이 제 조각 안에 있고 조각이 끝나기 2초(자른 뒤의 시간) 전보다 앞인지 본다. 조각마다 구간이 끝나는 곳보다 앞에서 시작하는지, 녹화 원본의 길이(`ffprobe`) 안에서 끝나는지, 길이(`dur`)를 정한 자막이 다음 자막이 시작하기 전에 끝나는지도 본다. 아니면 하나마다 한 줄로 말하고 아무것도 자르지 않는다(종료 값 2). 자막이 없는 조각은 자막 없이 자른다(플러그인은 자막이 없으면 카메라의 샷 이름을 대신 넣는데, 그것은 녹화하는 사람의 메모다).

누르고 치는 장면은 1.25배로, 기다림(심사, 허브 화면의 긴 작업, 경보, Claude Code가 일하는 동안)은 4배로 따로 자른다. 몇 초에 끝나는 작업(`23-reject`의 반려, `44-attach`의 붙이기)은 제 조각 안에서 1.25배로 둔다. 한 장면의 조각끼리는 페이드 없이 바로 이어 붙이고, 장면과 카드 사이만 0.4초 페이드한다. 긴 기다림은 시작이나 끝만 남기고, 터미널에서 다음 명령을 치는 동안도 잘라 낸다(그래서 다음 명령은 다 쳐진 채로 나타난다). `52-incident`와 `57-back`의 심사는 끝만 보인다. `56-cause`에서 Claude Code의 답 첫 줄(원인)은 화면 맨 위에 0.8초만 가만히 있어서, 그 0.8초의 실제 프레임을 0.13배로 느리게 튼다. 프레임은 고치거나 합성하지 않는다.

2026-11-23에 이 파일로 만든 릴은 이렇다(`ffprobe`, 모두 1920x1080, H.264, 30fps). 전체 릴 10분 50초(649.7초), 1단계 릴 1분 39초(준비를 포함한다), 2단계 2분 28초, 3단계 55초, 4단계 1분 56초, 5단계 3분 31초다. `build.py --check`가 찍는 길이는 조각마다 구간의 길이를 속도로 나누고 카드의 초를 더해 셈한 것이라(전체 릴 10:48, 2단계 2:27) 만든 파일보다 조금 짧다. 녹화 24개(장면은 25개다. `11-find`와 `12-make`는 한 녹화를 나눈 것이다)를 조각 67개로 잘랐고 자막은 60개다. `poster.png`는 전체 릴의 128.7초 프레임이다. 2단계에서 `release_review`의 심사가 일곱 단계를 지나는 화면(단계마다의 AWS 서비스와 하는 일)과 그 자막이다. 2026-11-24에 자막 아홉 개의 낱말을 바꾸고(판은 버전으로, 저절로는 자동으로, 짚습니다는 찾습니다로) 여섯 릴을 다시 만들었다. 길이와 프레임 수는 2026-11-23의 릴과 같다.

## 해설이 든 영상 (`build.py --voice`)

같은 여섯 릴을 한국어 해설과 강조 상자를 넣어 따로 만든다. 소리 없는 릴은 그대로 두고, 해설이 든 릴은 이름 끝에 `-voice`가 붙는다(`hosting-hub-main-ko-voice.mp4`, `hosting-hub-stage-<1..5>-ko-voice.mp4`).

해설이 든 영상에는 demo-video 1.4.0 이상이 필요하다(`edit_demo.py voice`, `reel`이 받는 음성과 그림 조각, `check_demo.py`). 1.4.0은 2026-11-24 현재 아직 공개되지 않았다. `DEMO_VIDEO_PLUGIN`이 `check_demo.py`가 없는 폴더(1.3.0이 그렇다)를 가리키면 빌드는 1.4.0 이상이 필요하다고 한 줄로 말하고 멈춘다(종료 값 2).

```
python3 demo_video/scripts/build.py --voice --check     # 해설과 상자를 검사하고 스크립트 파일, 해설의 줄, 릴의 목록을 쓴다. AWS를 부르지 않는다
AWS_REGION=<리전> python3 demo_video/scripts/build.py --voice     # 그다음 클립, 음성, 릴과 그 검사 (DEMO_VIDEO_PLUGIN이 필요하다)
```

`--voice --check`는 소리 없는 `--check`와 달리 녹화 원본과 그 카메라 기록(`out/raw/`)을 읽고 `ffprobe`를 쓴다. 조각을 자막마다 나누고 해설이 시작하는 곳을 셈하려는 것이다. 그래서 녹화 원본이 없는 새 checkout에서는 어느 원본이 없는지 말하고 아무것도 쓰지 않고 멈춘다(종료 값 1. 2026-11-24에 원본이 없는 출력 폴더로 돌려 보았다).

- 해설(`say`)은 자막과 카드에 붙어 있고, 자막처럼 이 파일에 있다. 해설은 그 해설이 나오는 동안의 프레임에 보이는 것이나 이 저장소의 README에 이미 적힌 것만 말한다. 문장은 합니다체이고, 화면의 이름(`release_review`, `AWS CodeBuild` 같은)과 숫자는 `READINGS`의 읽는 법으로 바꿔 합성기에는 한글만 보낸다. 무엇을 쓰기 전에 어긋난 해설과 상자를 하나마다 한 줄로 말하고 멈춘다(종료 값 2). 상자에서 이 검사가 찾는 것은 `what`이 없거나 상자 수와 맞지 않는 것, `box_delay`와 `box_dur`의 값, 숫자로 준 상자가 네 숫자가 아니거나 1920x1080 프레임 밖에 있는 것이고, 상자가 자막의 띠에 걸리는 것, 상자가 보이는 동안 카메라가 움직이는 것, `box_dur`가 자막보다 길게 가거나 `box_delay`가 길어 상자가 나타나지 못하는 것, 카메라 기록의 상자(`shot:`, `mark:`)에 크기가 없는 것은 플러그인의 클립 단계가 찾는다(스크립트 파일을 쓰고 그 앞의 클립을 자른 뒤, 음성을 합성하기 전에 멈춘다).
- 음성은 Amazon Polly다(음성 `Seoyeon`, 엔진 `generative`, 언어 `ko-KR`). 플러그인의 `edit_demo.py voice`가 해설 한 줄마다 AWS CLI의 `aws polly synthesize-speech`를 한 번 부르고, 리전은 환경 변수에서 온다. 글이 바뀌지 않은 줄은 다시 합성하지 않는다(`out/voice/ko/voice.json`).
- 해설이 든 자막은 그 조각의 끝까지 남고, 해설은 자막이 뜬 0.3초 뒤에(카드에서는 0.3초에) 시작한다. 해설이 제 조각보다 길면 같은 장면에서 뒤따르는 자막 없는 조각(기다림, 작업의 나머지) 위로 이어진다. 그래도 해설이 남으면 릴은 해설이 지나는 마지막 조각, 곧 다음 해설의 조각 바로 앞 조각의 마지막 프레임을 해설이 끝날 때까지 그대로 보인다. 뒤따르는 자막 없는 조각이 없으면 그것은 제 조각의 마지막 프레임이다. 두 해설 사이는 0.6초 이상 비게 하고, 모자라면 다음 해설의 조각 바로 앞 조각의 마지막 프레임을 그만큼 더 보인다. 프레임은 고치거나 합성하지 않는다. 마지막 해설 뒤에는 1초가 남는다. 릴의 소리는 해설뿐이고 통합 음량 −16 LUFS, true peak −1.5 dBTP 이하로 맞춘다.
- 강조 상자는 허브 화면과 Claude Code의 화면에서 해설이 한 곳을 가리키는 자막(실패한 단계, 레코드의 상태, 표의 줄, 정책의 줄 같은)에 있다(`box`, 상자마다 무엇을 가리키는지 `what`). 빨간 테두리 8px와 그 바깥의 어두운 선 2px이고, 카메라가 멈춘 뒤에 나타나며 카메라가 움직이는 동안에는 보이지 않는다(그 전에 `box_dur`로 끝낸다). 개발자의 셸과 사용자의 셸의 줄에는 상자가 없다. 글자 줄 사이가 몇 px뿐이라(2026-11-24에 두 셸의 프레임에서 쟀을 때 개발자의 셸은 2~7px, 사용자의 셸은 2~10px였다) 테두리와 바깥 선, 6px의 여유를 둔 상자(한쪽에 16px)가 위아래 줄을 지나기 때문이다. 허브 화면과 Claude Code의 화면에서도 해설이 가리키는 곳마다 상자가 있지는 않다. 예를 들어 그것이 자막 밑에 있거나, 이웃한 것과 몇 px밖에 떨어지지 않았거나, 카메라가 그 위에 2.5초도 머물지 않는 곳에는 없다.
- 결과물은 `out/` 아래다. `scripts/ko-voice/`와 `clips/ko-voice/`(해설이 든 조각. 자막이 둘 이상인 조각은 자막마다 나눈다), `voice/ko/`(줄마다의 mp3, `voice.json`, `lines.json`, `readings.json`), `reels/hosting-hub-<릴>-ko-voice.json`, `.mp4`, `.voice.json`(목록, 릴, 해설이 놓인 시각과 경고), `reports/<릴>-ko-voice/`(검사의 결과와 확인 페이지 `review.html`). 조각을 나누므로 해설이 든 빌드는 한 장면의 조각에 번호를 새로 매기고, 바뀐 이름을 `--voice --check`가 찍는다(예: `21-review.4 -> 21-review.6`). 이 절에 적은 조각 이름(`21-review.5`, `21-review.7` 같은)은 이 새 번호다.
- 카드의 그림은 소리 없는 빌드가 그린 것(`out/cards/ko/<카드>.png`)을 그대로 쓰고, 그림이 없는 카드만 그린다. 그러니 카드의 글을 바꾸면 소리 없는 빌드(`build.py`, `--check` 없이. `--check`는 그림을 그리지 않는다)를 먼저 돌려 그림을 다시 그린 뒤에 `--voice`를 돌린다. 아니면 해설이 든 릴에 바꾸기 전의 그림이 나온다.
- 플러그인의 단계(클립, 카드, 음성, 릴, `boxes`, `sheet`)가 실패하면 빌드는 그 단계가 찍은 줄 다음에, 어느 단계가 어느 조각이나 카드나 릴에서 실패했는지 한 줄로 말하고 멈춘다(종료 값 2). `audit`이 실패했을 때는 아래와 같다.
- 릴마다 플러그인의 `check_demo.py`로 셋을 본다. `audit`은 릴에서 소리가 나는 구간을 찾아, 해설마다 그 mp3에서 소리가 나는 곳이 릴에서 계획한 자리와 앞뒤 0.25초 안에서 맞는지, 해설을 계획하지 않은 곳에 소리가 없는지, 영상과 소리의 길이가 0.1초 안에서 같은지, 통합 음량이 −16 LUFS에서 1.5 LU 안인지 본다. 하나라도 어긋나면 빌드가 멈춘다. true peak가 −1.5 dBTP를 넘으면 경고만 한다. `boxes`는 상자마다 테두리 밑이 글자나 선을 지나는지(`crosses`), 빨간 것 위에 있는지(`low_contrast`), 상자가 보이는 동안 그 안의 화면이 바뀌는지(`moved`)를 재서 표시한다. `sheet`는 해설마다 한 줄의 확인 페이지를 쓴다(해설의 시작 + 0.5초, 가운데, 끝 − 0.2초의 프레임, 상자의 확대, 자막과 해설, 그 구간의 소리). 릴의 계획 파일(`reels/hosting-hub-<릴>-ko-voice.voice.json`의 `warnings`)에는 한 번에 6초가 넘게 멈춘 프레임, 릴의 30 %가 넘는 멈춘 프레임, 14초가 넘는 해설, 그리고 음량을 한 번의 증폭으로 맞출 수 없어 압축으로 맞춘 것이 경고로 적힌다(빌드를 멈추지는 않는다).
- 한계: `audit`이 재는 것은 소리의 자리, 길이, 음량과 true peak뿐이다. 해설의 말이 맞게 읽혔는지, 발음이 자연스러운지는 모른다. 확인 페이지의 상자 확대는 해설의 가운데 프레임에서 자르므로, 상자가 그보다 먼저 끝나면 확대에 상자가 없다(그때는 프레임을 따로 보아야 한다).

2026-11-24에 이 파일로 만든 해설이 든 릴이다(`ffprobe`, 모두 1920x1080, H.264, 30fps, AAC 소리 하나).

| 릴 | 길이 | 크기 | 멈춘 프레임 |
|---|---|---|---|
| 전체 | 15분 16초(915.7초) | 97.6 MB | 29.0 % |
| 1단계(준비를 포함한다) | 2분 57초 | 19.2 MB | 43.8 % |
| 2단계 | 3분 5초 | 22.4 MB | 20.3 % |
| 3단계 | 1분 19초 | 8.1 MB | 29.7 % |
| 4단계 | 2분 46초 | 17.1 MB | 30.1 % |
| 5단계 | 4분 33초 | 30.2 MB | 22.6 % |

- 해설은 70개(카드 10, 자막 60)이고 상자는 조각 28개에 29개다. 리전은 us-west-2였다. 처음 돌릴 때 70줄(5,698자)을 합성했다. 해설 둘이 14초가 넘어서(`21-review.5` 14.4초, `card-closing` 15.0초) 그 둘의 글을 줄이고 다시 돌렸고, 그때는 그 두 줄(182자)만 합성했다.
- 여섯 릴 모두 `audit`을 통과했다. 해설마다 릴에서 소리가 잡힌 자리는 그 mp3의 소리로 셈한 자리에서 앞뒤 0.013초 안이었고, 영상과 소리의 길이는 0.01초 안에서 같았다. 통합 음량은 여섯 릴 모두 −16.0 LUFS, true peak는 −1.5~−1.6 dBTP였다.
- 해설끼리의 음량 차이는 음성 파일에 이미 있다. 해설 70개의 mp3는 −23.8~−22.0 LUFS이고(ffmpeg `ebur128`), `audit`이 한 릴 안에서 해설마다 따로 잰 음량은 가장 큰 것과 가장 작은 것이 1.1~1.8 LU 차이였다. 3단계와 4단계 릴은 모든 해설을 한 번에 6.7~6.8 dB 키웠다. 나머지 네 릴(전체, 1단계, 2단계, 5단계)은 한 번의 증폭으로 −16 LUFS에 맞추면 true peak가 −1.5 dBTP를 넘어서 플러그인이 압축으로 맞췄고, 그 압축은 릴의 처음 1분쯤의 해설을 덜 키웠다. 전체 릴의 첫 해설(`card-intro`)은 5.2 dB를 키워 다른 해설(대개 6.9 dB)보다 1.7 dB쯤 작고, 5단계 릴의 첫 해설(`card-ch5`)은 6.1 dB로 그 릴의 다른 해설(대개 7.0~7.1 dB)보다 0.9 dB쯤 작고, 그다음 두 해설(`51-usage.1` 6.6 dB, `51-usage.2` 6.8 dB)도 조금 덜 키웠다. 1단계와 2단계 릴에서는 그 차이가 0.6 dB 이하다. 키운 양은 mp3의 음량과 `audit`이 릴에서 잰 그 해설의 음량의 차이로 셈했다.
- `boxes`는 상자 29개 어디에도 표시를 하지 않았다. 만든 사람은 처음 만든 전체 릴에서 상자마다 그것이 보이는 동안의 프레임을 보았고(상자는 `what`이 말하는 것을 둘러싸고 글자를 지나지 않았다), 해설 둘을 고쳐 다시 만든 전체 릴에서는 그 가운데 셋(`21-review.7`, `33-record.3`, `57-back.3`)을 다시 보았다. 확인 페이지는 처음 만든 릴의 것에서 전체 릴의 70줄과 단계마다의 릴의 첫 줄과 마지막 줄을 보았고, 다시 만든 릴의 것에서는 글을 고친 두 줄(`21-review.5`, `card-closing`)을 보았다. 두 번째 빌드는 조각 78개를 같은 스크립트로 모두 다시 잘랐고, 고친 두 줄 말고는 음성 파일을 그대로 썼다.
- 남은 경고는 릴의 계획 파일에 적힌 것이다. 한 번에 6초가 넘게 멈춘 프레임은 전체 릴에서 여덟 곳이다(카드 `card-intro` 7.7초, `card-ch2` 6.4초, `card-closing` 6.2초와 조각 `00-home.4` 7.1초, `00-home.5` 7.0초, `11-find.2` 7.0초, `12-make.4` 6.0초, `57-back.1` 6.1초). 단계마다의 릴에서는 그 가운데 그 단계에 든 것(1단계 릴 넷, 2단계 릴 `card-ch2`, 5단계 릴 `57-back.1`)과 4단계 릴의 `card-compare` 6.1초다. 멈춘 프레임이 릴의 30 %를 넘은 것은 1단계 릴(44 %, 177.1초 가운데 77.5초)과 4단계 릴(30 %, 165.8초 가운데 49.9초)이다. 1단계 릴은 해설에 비해 화면이 짧다. 그리고 압축으로 맞춘 네 릴에는 그 알림이 있다.
- 만든 사람은 소리를 듣지 않았다. 확인한 것은 소리가 계획한 자리에 있다는 것(`audit`)과, 합성기에 보낸 글 70개가 이 파일의 해설에 `READINGS`를 적용한 것과 같다는 것(`voice.json`의 `spoken`)이다.

## 녹화 (`scenes/`)

장면마다 폴더 하나에 `storyboard.mjs`(플러그인의 `record_demo.mjs`가 부르는 함수)가 있고, 녹화는 `scenes/record.sh`로 한다.

```
export DEMO_VIDEO_PLUGIN=<플러그인의 scripts 폴더> PLAYWRIGHT_ROOT=<node_modules/playwright가 있는 폴더>
demo_video/scenes/record.sh <장면> [최대 초] [--lang ko]      # 예: record.sh 00-home, record.sh 21-review 720
```

- 스토리보드는 찍는 화면을 한 줄(`export const surfaces = ['hub'];`)로 적는다. `hub`는 허브 화면(`make ui`, `127.0.0.1:8300`), `dev`는 개발자 PC의 터미널(`tools/dev_pc/run.sh term`, `127.0.0.1:7681`), `user`는 사용자의 셸(`tools/user_shell.sh up`, `127.0.0.1:7682`)이다. `record.sh`는 그 화면이 답하지 않으면 띄우는 명령을 말하고 멈춘다.
- 녹화는 `out/raw/<장면>.webm`, 카메라 기록 `out/raw/<장면>.camlog.json`, 화면의 글 `out/raw/<장면>.texts.txt`로 남는다. 화면의 글은 샷마다 하나이고, Claude Code 장면에서는 스토리보드가 샷 사이에 읽은 화면도 처음 본 것마다 하나씩 들어간다. 같은 장면을 다시 찍으면 앞의 것은 `out/raw/old/`로 옮긴다. 끝나면 샷, 메모, 선택자가 아무것도 찾지 못한 샷을 찍고, 화면의 글에 12자리 숫자, 이메일 주소, AWS 액세스 키 ID의 모양(`AKIA`나 임시 키의 `ASIA` 다음에 대문자나 숫자 16자)이 있으면 그 줄을 찍고 종료 값 1로 끝난다(`lib/check_texts.sh`. 개발자 PC의 이름 `dev@dev-pc`는 가리고 그 줄의 나머지도 검사한다). 화면의 글은 컨테이너의 프로그램이 고른 글이므로, 찍는 줄은 제어 문자를 빼고(탭과 줄바꿈은 남긴다) 숫자와 키를 가린 뒤 300자에서 자른다.
- 스토리보드는 먼저 허브가 그 장면에 필요한 상태인지 본다(`lib/state.mjs`가 `lib/hub_state.py`로 카탈로그의 record와 상태, 도는 심사, 전사 정책의 모드, 커스텀 가드레일, 멈춘 에이전트를 읽는다. 녹화하는 사람의 자격 증명으로 읽기만 한다). 아니면 무엇이 다른지 한 줄로 말하고 아무것도 하지 않는다.
- 장면이 치거나 기다리는 글은 모두 `lib/texts.mjs`에 언어별로 있다. 스토리보드는 `--lang`을 읽는다. 지금은 한국어만 찍는다.
- 허브 화면의 버튼은 폼 POST이고 303으로 페이지를 다시 연다. 작업이 끝나면 페이지가 한 번 새로 읽힌다. 카메라는 페이지 안에 있으므로 `lib/hub.mjs`가 새 페이지마다 카메라를 다시 넣는다.
- 한 에이전트의 심사 페이지에서 심사를 기다리는 반복(단계가 바뀔 때마다 메모하고 다시 잡는다. 레코드가 `APPROVED`이고 심사가 `SUCCEEDED`이거나, 심사가 다르게 끝나거나, 시간이 다 되면 멈춘다)은 `lib/hub.mjs`의 `waitForReview` 하나다(`21-review`, `25-approved`, `52-incident`, `57-back`). 심사의 끝은 그 심사가 도는 것을 본 뒤에만 센다. 페이지가 처음에 앞선, 끝난 심사를 보일 수 있기 때문이다. 2026-11-23의 녹화는 모두 이 함수로 옮기기 전의 스토리보드로 찍었고, 옮긴 뒤의 네 스토리보드는 돌려 보지 않았다(허브를 지운 뒤에 옮겼다). 옮기면서 `21-review`와 `25-approved`가 바뀐 것은 둘이다. 끝을 심사가 도는 것을 본 뒤에만 세고, 레코드가 `APPROVED`여도 심사가 `SUCCEEDED`가 될 때까지 기다린다(전에는 레코드만 보았다). 그날의 두 녹화에서는 심사가 처음 본 때부터 돌고 있었고, 레코드의 `APPROVED`와 심사의 `SUCCEEDED`가 같은 메모 시각에 나왔다(카메라 기록). 그러니 지금의 함수로도 같은 때에 끝났을 것이다(돌려 보지 않았다).

장면과 그 장면이 필요로 하는 허브의 상태다(스토리보드가 맨 먼저 확인한다). 한 장면이 남긴 상태가 다음 장면의 시작이다.

| 장면 | 화면 | 하는 일 | 필요한 상태 | 남기는 상태 |
|---|---|---|---|---|
| `00-home` | 허브 화면 | 홈: 수, 두 흐름의 그림, 플랫폼 구성, 카탈로그 | `docs_adk`, `spec_assistant`, `parts-tools` 승인, `quality_agent`와 `release_review` 없음, 전사 정책 꺼짐, 가드레일 떨어짐 | 바꾸지 않는다 |
| `11-find` | 개발자 PC | 한 Claude Code 세션: 카탈로그의 MCP 검색 도구로 부품 규격 도구를 찾고(`11-find`), 표준 템플릿으로 `quality_agent`의 파일을 만든다(메모 `make_asked`부터 `12-make`). 실행하거나 올리지 않는다 | `parts-tools` 승인, 두 에이전트 없음 | 컨테이너의 `dev_team/quality_agent`(Claude Code가 만든 것). 다음 장면 전에 `run.sh agent quality_agent` |
| `13-submit` | 개발자 PC | `publish release_review`, `publish quality_agent v1-vulnerable` | 두 에이전트 없음, 작업 폴더에 리포의 `quality_agent` | 두 record 승인 대기, 심사 둘이 돈다. 곧바로 `21-review`를 찍는다 |
| `21-review` | 허브 화면 | 두 심사를 처음부터 끝까지: `quality_agent`는 Scan에서 실패, `release_review`는 일곱 단계를 지나 `APPROVED` | 두 record 승인 대기, `release_review`의 심사가 돈다 | `release_review` 승인, `quality_agent` 승인 대기(실패한 심사) |
| `22-works` | 사용자의 셸 | `ask release_review --file demo_scenes/inputs/change-ok.txt` | `release_review` 승인 | 바꾸지 않는다 |
| `23-reject` | 허브 화면 | 실패한 단계, 스캔이 찾은 줄, 사유를 적고 반려(`REHEARSE=1`이면 누르지 않는다) | `quality_agent` 승인 대기, 도는 심사 없음 | `quality_agent` 반려 |
| `24-again` | 개발자 PC | 고친 판의 의존성을 보이고 `publish quality_agent` | `quality_agent` 반려 | 승인 대기, 심사가 돈다. 곧바로 `25-approved`를 찍는다 |
| `25-approved` | 허브 화면 | 고친 판의 심사가 일곱 단계를 지나 `APPROVED` | `quality_agent`의 심사가 돈다 | `quality_agent` 승인 |
| `26-answers` | 사용자의 셸 | `ask quality_agent "What is the spec of part P-100?"` | `quality_agent` 승인 | 바꾸지 않는다 |
| `31-logonly` | 허브 화면 | 전사 정책 페이지에서 `guard_prompt`를 기록 모드로 건다(버튼 한 번, 작업의 줄, 에이전트 게이트웨이의 정책 줄). `REHEARSE=1`이면 누르지 않는다 | 에이전트 셋 승인, 전사 정책 꺼짐, 가드레일 떨어짐, 멈춘 것 없음 | 전사 정책 기록 모드(`LOG_ONLY`) |
| `32-passes` | 사용자의 셸 | 숨은 지시가 든 변경 설명을 `release_review`에 보낸다: 200 | 기록 모드 | 바꾸지 않는다(정책이 그 요청을 센다). 곧바로 `33-record`를 찍는다 |
| `33-record` | 허브 화면 | 기록 모드의 집계가 `release_review`의 걸린 요청 1을 보일 때까지 기다린다(180초까지) | 기록 모드 | 바꾸지 않는다 |
| `41-enforce` | 허브 화면 | 적용 모드로 올린다(버튼 한 번, 같은 정책의 모드가 바뀐다). `REHEARSE=1`이면 누르지 않는다 | 기록 모드 | 적용 모드(`ACTIVE`) |
| `42-blocked` | 사용자의 셸 | 같은 파일을 `release_review`와 `docs_adk`에 보낸다: 둘 다 403과 게이트웨이의 문장 | 적용 모드 | 바꾸지 않는다 |
| `43-before` | 사용자의 셸 | 코드명이 든 요청은 200, 검사 질문의 답에 사번이 보인다(샘플 도구의 만든 값) | 적용 모드, 가드레일 떨어짐 | 바꾸지 않는다 |
| `44-attach` | 허브 화면 | 커스텀 가드레일을 붙인다(버튼 한 번). 떼지 않는다(5단계까지 붙어 있다). `REHEARSE=1`이면 누르지 않는다 | 가드레일 떨어짐 | 가드레일 붙음 |
| `45-after` | 사용자의 셸 | `43-before`와 같은 두 요청: 코드명은 403과 인터셉터의 문장, 검사 질문의 답에는 사번 대신 `{employee_id}` | 가드레일 붙음 | 바꾸지 않는다 |
| `51-usage` | 허브 화면 | 에이전트 페이지: 에이전트마다의 사용량, 도구마다의 호출, 도구 호출 경보 | 에이전트 셋 승인, 멈춘 것 없음 | 바꾸지 않는다 |
| `52-incident` | 개발자 PC, 허브 화면, 사용자의 셸 | 한 녹화: `publish quality_agent v2-loop`, 그 심사를 `APPROVED`까지(실시간, 단계마다 메모), `ask quality_agent "What is the result of inspection Q-1002?" --timeout 60`에 답이 오지 않는다 | `quality_agent` 승인, 멈춘 것 없음, 작업 폴더에 리포의 `quality_agent`(`run.sh agent quality_agent`) | 되풀이하는 판이 승인되어 돈다. 샷 `asked`가 화면의 글(`out/raw/52-incident.texts.txt`의 `== <초> asked` 줄)에 나오면 곧바로 `53-alarm`을 찍는다(2026-11-23에는 그 줄을 기다리는 셸 한 줄로 띄웠다) |
| `53-alarm` | 허브 화면 | 경보의 막대가 임계값을 넘고 상태가 `ALARM`이 될 때까지(420초까지, 넘은 때와 바뀐 때에 메모) | `quality_agent` 승인, 멈춘 것 없음 | 바꾸지 않는다 |
| `54-stop` | 허브 화면 | `quality_agent`만 멈춘다(버튼 한 번, 작업의 줄). `REHEARSE=1`이면 누르지 않는다 | 멈춘 것 없음 | `quality_agent` 멈춤 |
| `55-neighbours` | 사용자의 셸 | `quality_agent`는 403, `release_review`와 `docs_adk`는 200 | `quality_agent` 멈춤 | 바꾸지 않는다 |
| `56-cause` | 개발자 PC | 한 Claude Code 세션: 왜 같은 도구를 계속 불렀는지 로그(`logs`)와 코드를 읽고 찾는다. 고치거나 돌리지 않는다 | `quality_agent` 멈춤 | 바꾸지 않는다 |
| `57-back` | 개발자 PC, 허브 화면, 사용자의 셸 | 한 녹화: `publish quality_agent`(고친 판), 멈춘 채로 심사가 `APPROVED`까지, 에이전트 페이지에서 재개(버튼 한 번), `ask quality_agent`가 답한다. `REHEARSE=1`이면 에이전트 페이지만 잡는다 | `quality_agent` 승인(되풀이하는 판)이고 멈춤, 작업 폴더에 리포의 `quality_agent`(이 장면 전에 `run.sh agent quality_agent`, 아래) | 고친 판이 승인되어 돈다 |

`57-back`은 컨테이너의 `dev_team/quality_agent`를 그대로 올린다. 바로 앞의 Claude Code 세션(`56-cause`)은 그 폴더에 묻지 않고 쓸 수 있으므로, 리포의 에이전트를 다시 넣는 `run.sh agent quality_agent`를 이 장면 전에 돌린다. 2026-11-23의 5단계 녹화 기록에서 그 명령은 `52-incident` 전(UTC 14:01)에 한 번 돌렸고, `56-cause`와 `57-back` 사이에 돌린 기록은 없다. 그날 `56-cause`의 요청은 파일을 고치지 말라고 했고, Claude Code의 답은 요청대로 파일을 고치지 않았다고 했다. 올리기 전에 이 장면이 스스로 확인하는 것은 `dev_team/quality_agent/agent.py`에 `asking again`이 없는지(`grep`)뿐이다.

### 사용자의 셸 (`tools/user_shell.sh`)

팀의 사용자가 호스팅된 에이전트를 부르는 터미널이다. `user_shell.sh up`은 ttyd를 `127.0.0.1:7682`에서만(`-i lo`, 다른 출처의 연결은 받지 않는다 `-O`) 띄우고, 페이지를 열 때마다 bash가 새로 뜬다. 프롬프트는 `사용자 $ `, 시작 폴더는 리포의 루트, PATH의 맨 뒤에 `demo_scenes/`가 있어서 `ask …`로 친다. rc 파일을 읽지 않고 기록(history)을 남기지 않는다. 허브에는 사용자 역할이 따로 없다(사용자는 에이전트 게이트웨이를 부를 수 있는 IAM 주체다). 그래서 이 셸은 녹화하는 사람의 자격 증명으로 돈다. 이 PC에서 `127.0.0.1:7682`에 닿는 것은 그 셸을 얻으므로 녹화할 때만 띄우고 끝나면 `user_shell.sh down`으로 멈춘다.

### Claude Code 장면

Claude Code가 화면에 찍는 것은 믿지 않는다. 묻는 말의 글(셸 명령, 파일 경로)은 다른 에이전트가 정하므로 스토리보드(`lib/claude.mjs`)는 그것을 판단하지 않고, 어떤 물음에도 Yes를 고르지 않는다. 스토리보드는 화면을 보고 언제 넘어갈지와 카메라를 어디에 둘지만 정한다. 묻는 창은 선택지 줄로 알아본다. 선택지 줄은 표시 `❯`가 붙은 번호 줄(`❯ 1. …`, 글은 무엇이든)과, 표시 없이 Yes나 No로 시작하는 번호 줄(`2. No` 같은 줄)이다. 그래서 Claude Code가 스스로 그리는 물음(선택지의 글을 다른 에이전트가 쓴다)도 묻는 창이다. 그런 물음의 화면은 시험(`tests/test_demo_video.py`의 `OWN_QUESTION`)에 손으로 적은 것이고, 녹화에서 그런 창을 본 적은 없다. 표시가 없고 Yes나 No로 시작하지 않는 번호 목록(Claude Code의 답 안의 목록)은 선택지 줄로 보지 않는다. 화면에 묻는 창이 있으면 그 창을 잡아 카메라에 보이고(묻는 줄은 선택지 위로 몇 줄 안에서 찾으므로 두 줄로 접혀도 된다), Esc(No)를 누르고, 장면이 정한 문장(어떻게 계속할지)을 보낸다. 스토리보드가 본 묻는 창에 누르는 키는 Esc뿐이다. 글을 붙여 넣는 것과 Enter(붙여 넣은 글을 보낼 때와 셸에서 `claude`를 띄울 때)는 바로 전에 화면을 보아 선택지 줄을 하나도 찾지 못했을 때만 한다. 찾으면 Esc를 누르고 다시 보고, 그래도 있으면 한 줄로 말하고 장면을 멈춘다. 그래서 Claude Code는 파일을 셸 명령이 아니라 자기 쓰기 도구로 만들고(작업 폴더의 맨 위에 선 셸에서는 `dev_team/` 아래 쓰기를 묻지 않는다), 읽기는 자기 읽기 도구와 묻지 않고 허락된 `search`, `logs`, `ls`, `cat`으로 한다. 화면을 본 뒤 키를 누르기 전에 묻는 창이 새로 뜨면, 그 키(붙여 넣은 글이나 Enter)는 그 창이 받는다(Enter면 그 창에서 표시가 붙은 선택지를 고른다). 코드가 그렇게 되어 있고, 2026-11-23의 녹화에서 그런 일은 보지 못했다.

2026-11-23의 `11-find`는 이 스토리보드의 앞선 꼴로 찍었다. 그 꼴은 묻는 말의 글을 읽어 판단했고, 그 장면에서 읽기만 하는 셸 명령 넷(`cd`, `ls`, `cat`, `grep`, `sed -n`, `head`, `tail`, `for` 문 안의 `echo`와 `cat`)에 Yes, 앞의 43줄이 가려진 명령(폴더를 만들고 here-document로 파일을 쓰는 것)에 No를 골랐다. 그 꼴은 Claude Code가 그리는 창에서 코드를 돌리거나 파일을 쓰는 명령에도 Yes를 할 수 있었다(그 꼴의 판단 함수에 녹화된 창의 모양으로 명령을 넣어 보면 `python3 quality_agent/agent.py`, `publish quality_agent`, `cp quality_agent/agent.py ../demo_scenes/search`에도 Yes를 돌려주었다). 지금의 스토리보드라면 다섯 물음 모두에 No다.

2026-11-23의 녹화(`11-find`, UTC 11:50~12:07, 다섯 번 찍었다)에서 본 것이다. 첫 번째에는 "그 도구의 record를 보여 주세요"라는 요청에 Claude Code가 record의 ARN(계정 ID가 들어 있다)을 표로 보였고, `record.sh`의 글 검사가 그것을 잡아 그 녹화를 버렸다. 그 뒤로 요청은 도구의 이름, 설명, 입력을 묻는다. 그다음 세 번은 스토리보드가 묻는 말에 잘못 No를 고른 것(따옴표 안의 `|aws`를 명령으로 읽은 것, 긴 미리보기로 경로가 화면 밖에 있던 파일, 두 줄로 접힌 `cp` 명령)이어서 고치고 다시 찍었다. 다섯 번째에서 Claude Code는 읽기 넷을 묻고(Yes), 앞의 43줄이 화면에 보이지 않는 긴 명령(`mkdir`, `cp`, here-document로 파일 쓰기)을 물었고(No), 그 뒤 파일 다섯을 `dev_team/quality_agent/`에 묻지 않고 썼다. 아무것도 실행하거나 올리지 않았다.

같은 날 Claude Code가 셸에서 `cd dev_team`을 한 뒤에는 `dev_team/` 아래의 파일을 만들 때도 물었고, 화면의 경로는 `dev_team/`을 기준으로 보였다(`quality_agent/agent.json`). 12:54~12:56(UTC)에 컨테이너의 대화형 세션에서 확인했다. `cd demo_scenes` 뒤에 편집 도구로 `search`를 고치는 것과, `cd dev_team` 뒤에 `dev_team/x/.claude/skills/y/SKILL.md`를 쓰는 것은 둘 다 `File is in a directory that is denied by your permission settings.`로 거부되었다. 거부 규칙은 `cd` 뒤에도 맞았다. `dev_team/quality_agent/` 아래에 쓰는 것은 `cd` 없이는 묻지 않았고(파일이 생겼다), `cd dev_team` 뒤에는 절대 경로로 써도, 상대 경로로 써도 물었다(No로 답해서 생기지 않았다). 그러니 `cd` 뒤에 맞지 않게 되는 것은 허락 규칙 `Edit(./dev_team/**)`이고, 그때 Claude Code는 거부하지 않고 묻는다. 허락 규칙은 그대로 두었다. 작업 폴더 밖의 폴더로 `cd`한 뒤 `<그 폴더>/dev_team/` 아래에 쓰는 것(그 규칙이 셸의 폴더를 따라 그곳에서 묻지 않게 되는지)은 해 보지 않았다. Claude Code는 `cd`만 있는 셸 명령은 묻지 않고 돌렸다.

2026-11-23의 `56-cause`(UTC 14:14~14:19)는 같은 요청으로 세 번 찍었고 두 번째를 쓴다. 이 스토리보드는 묻는 말에 모두 No를 고른다. 세 번 모두 Claude Code는 `logs quality_agent 30`과 자기 읽기 도구로 읽었다. 첫 번째는 `dev_team/quality_agent/agent.py`(기본판)만 읽고 `variants/`를 보지 않아서, 로그의 `asking again`이 그 코드에 없다고만 답했다. 두 번째는 `cd …/dev_team/quality_agent && cat agent.json && find variants …`를 물었고(No), 그 뒤 `variants/v2-loop/agent.py`를 읽어 "v2-loop 판 run()에 재시도 횟수 제한이 없습니다"라고 답했다(PENDING인 동안 처음부터 다시 묻고, 끝나는 조건은 시간 기한 600초뿐이다). 그 답은 코드의 흐름만 읽은 것이 아니다. 그 판의 파일에 있는 주석, 횟수의 한도가 없어졌다는 문장("retry has lost its limit on the count")도 인용했다. 세 번째도 같은 원인을 찾았지만 에이전트의 README를 읽고 그 판이 일부러 사고를 내는 데모 판이라고 말해서 쓰지 않는다. 세 번은 같은 홈에서 돌았고, 그 홈에 있는 Claude Code의 메모 폴더는 보지 않았다(그날 `11-find` 전에 한 번 보려 했을 때 녹화하는 PC의 권한 시스템이 그 명령을 거부했다). 세 번의 화면에 메모를 읽는 것은 보이지 않았다. 5단계는 커스텀 가드레일을 붙인 채로 찍었다(되풀이 호출은 막히지 않았고, 경보가 울렸다).

## 개발자 PC (`tools/dev_pc/`)

개발자 장면을 찍는 PC다. Docker 컨테이너 하나이고, 이 안에서 개발자가 Claude Code로 에이전트를 만들고, 카탈로그를 검색하고, 에이전트를 올리고, 로그를 본다. 사용자는 `dev`, 호스트 이름은 `dev-pc`, 작업 폴더는 `/home/dev/work`, 프롬프트는 `개발자 $ `다.

이미지(`hub-dev-pc`)에 든 것과 버전이다. 모두 `Dockerfile`에 고정되어 있다.

| 도구 | 버전 | 쓰는 곳 |
|---|---|---|
| Claude Code (`@anthropic-ai/claude-code`) | 2.1.330 | 개발자의 코딩 도우미. Amazon Bedrock의 Claude로 돈다. Claude 계정으로 로그인하지 않는다. |
| `mcp-proxy-for-aws` | 2.0.0 (`uv tool install mcp-proxy-for-aws==2.0.0`) | 카탈로그(AWS Agent Registry)의 MCP endpoint에 SigV4로 서명해 Claude Code와 잇는다. |
| Python, uv | 3.13, 0.10.8 | 장면 명령(`search`, `publish`, `logs`)과 에이전트의 시험 |
| AWS CLI | 2.31.10 | 컨테이너의 셸 |

이 PC를 쓰려면 녹화하는 PC에 Docker, ttyd, jq, perl, AWS CLI가 있고, 허브가 올라와 있고(`make deploy`), 녹화하는 사람의 AWS 자격 증명이 개발팀 역할을 맡을 수 있고(`sts:AssumeRole`) `sts:GetFederationToken`을 부를 수 있어야 한다. `GetFederationToken`은 IAM 사용자의 장기 자격 증명으로만 부를 수 있다.

녹화와 편집에는 녹화하는 PC에 이런 도구가 있어야 한다(괄호 안은 2026-11-23에 쓴 버전이다). ttyd(1.6.3. `run.sh term`과 `tools/user_shell.sh up`), Playwright를 둔 node(v22.18.0. 플러그인의 `record_demo.mjs`, `PLAYWRIGHT_ROOT`), ffmpeg와 ffprobe(4.4.2. 자르기, 카드, 릴, 원본의 길이), Python 3(`scripts/build.py`), perl(`lib/check_texts.sh`), 그리고 플러그인의 `make_cards.py`가 쓰는 Pillow와 한글 글꼴(NanumSquare가 기본이고, 없으면 `fc-match`로 한국어 글꼴을 찾는다. 환경 변수 `DEMO_FONT_BOLD`, `DEMO_FONT_REGULAR`로 줄 수도 있다). ttyd는 1.7부터 `-W`(`--writable`)를 주지 않고 띄운 터미널이 입력을 받지 않는다(플러그인의 `term.mjs`도 `-W`로 띄우라고 적는다). 이 저장소의 스크립트는 `-W`를 주지 않으므로, ttyd 1.7 이상에서는 장면이 터미널에 아무것도 치지 못할 것이다. 1.7 이상으로는 해 보지 않았다.

### 컨테이너에 들어가는 자격 증명 둘

컨테이너에는 아래 둘만 들어간다. 녹화하는 사람의 자격 증명은 컨테이너, 이미지, 마운트한 폴더 어디에도 들어가지 않는다(`~/.aws`를 마운트하지 않는다).

| 자격 증명 | 만드는 법 | 유효 시간 | 쓰는 것 |
|---|---|---|---|
| 개발팀 역할의 임시 자격 증명(`developer.ini`) | `sts:AssumeRole`, 세션 이름 `developer` | 1시간(역할의 기본값) | 컨테이너의 기본 AWS 프로필. 셸, 장면 명령, MCP 프록시, Claude Code가 띄우는 도구가 모두 이것으로 돈다. |
| Claude Code의 Bedrock 토큰(`bedrock.json`) | `sts:GetFederationToken`, 이름 `hub-video-claude`, 세션 정책 `bedrock-policy.json.tmpl` | 4시간 | Claude Code 자신의 모델 호출. 설정 키 `awsCredentialExport`로 읽는다. 세션 정책은 영상의 두 모델(Claude Sonnet 5.5, Claude Haiku 4.5)의 추론 프로파일과 그 프로파일이 보내는 foundation model에 `bedrock:InvokeModel`과 `bedrock:InvokeModelWithResponseStream`만 허락한다. |

- 두 파일은 `demo_video/out/dev-pc/creds/`(폴더 700, 파일 600)에만 있고, 컨테이너에는 읽기 전용(`/run/dev-pc`)으로 들어간다. `run.sh creds`는 두 주체(계정은 `<ACCOUNT>`로 가린다)와 끝나는 시각만 찍고 키, 비밀 값, 토큰은 찍지 않는다. `run.sh forget`과 `run.sh down`이 두 파일을 지운다.
- 개발팀 역할에는 Bedrock 권한이 없고, Bedrock 토큰에는 모델 호출 말고는 권한이 없다.
- 한계: Bedrock 토큰 파일은 컨테이너의 사용자(Claude Code의 도구와 같은 사용자)가 읽을 수 있는 파일이다. `settings.json`의 `deny`(`Read(//run/dev-pc/**)`)가 Claude Code의 파일 읽기 도구를 막는다. 같은 모양의 `deny`는 묻지 않고 허락한 `cat`으로 그 파일을 읽는 셸 명령도 거부했다(2026-11-23, `/etc/hostname`을 막고 시험했다. 자격 증명 폴더로는 시험하지 않았다). 그래도 셸의 다른 길로 읽는 것까지 막는다고 보장하지는 못한다. 그 토큰으로 할 수 있는 것은 두 모델의 호출뿐이다.
- EC2 인스턴스에서는 컨테이너가 인스턴스 메타데이터 서비스에 닿을 수 있다(2026-11-23에 이 컨테이너를 돌린 EC2 인스턴스에서 닿았고, 그 인스턴스에는 역할이 있었다). `run.sh up`은 SDK가 그곳을 묻지 않게 하고(`AWS_EC2_METADATA_DISABLED=true`), 그 주소를 컨테이너의 네트워크에서 막는다. 막는 것은 root가 컨테이너를 띄운 직후 한 번 넣는 blackhole 경로다(`--cap-add NET_ADMIN`은 그 한 번을 위한 것이다). 컨테이너는 `no-new-privileges`로 돌아서 어느 프로세스도 권한을 더 얻지 못한다. 경로를 넣지 못하면 `up`은 컨테이너를 지우고 실패하고, `term`과 `check`는 경로가 없는 컨테이너를 거부한다. `run.sh check`는 사용자 `dev`의 `CapEff`가 0이고 `dev`가 그 경로를 지우지 못하는지(`Operation not permitted`) 보인다.

### 이 PC와 컨테이너의 경계

컨테이너가 이 PC에 쓸 수 있는 곳은 자기 홈 하나, `demo_video/out/dev-pc/home`(컨테이너의 `/home/dev`)이다. 자격 증명 폴더는 읽기 전용으로 들어간다. 홈 안에는 컨테이너 안의 어느 프로세스든 무엇이든 만들 수 있으므로(이 PC의 다른 폴더를 가리키는 심볼릭 링크도), `run.sh`는 홈 폴더를 만든 뒤로는 그 안의 것을 이 PC의 명령으로 만들거나 고치거나 지우지 않는다. 작업 폴더를 비우는 일, checkout을 넣는 일(이 PC가 표준 입력으로 보내는 tar), 설정 파일을 쓰는 일, `agent`가 에이전트를 바꿔 넣는 일은 모두 컨테이너 안에서 사용자 `dev`로(`docker exec`) 한다. 그곳에서는 링크가 컨테이너 안에서 풀리므로 이 PC의 다른 폴더에 닿지 않는다. `demo_video/out/dev-pc`, 홈, 자격 증명 폴더 자체가 심볼릭 링크면 `run.sh`는 한 줄로 거부한다. 홈(`demo_video/out/dev-pc/home/`)에는 컨테이너 안에서 쓴 파일(Claude Code의 메모와 대화 기록, 작업 폴더의 `CLAUDE.md`)이 있다. 이 저장소를 이 PC에서 코딩 도우미로 열 때는 도우미가 그 폴더를 읽지 않게 한다. 그런 도구는 그곳에서 찾은 `CLAUDE.md`를 지시로 받아들일 수 있다. 그 폴더에서 볼 것은 `docker exec`로 읽는다.

위의 경계는 파일의 것이다. 네트워크로는, 컨테이너가 Docker의 기본 bridge 네트워크에 있다(`run.sh up`이 네트워크를 따로 정하지 않는다). 그래서 인터넷에 닿고(2026-11-23에 컨테이너 안에서 Amazon Bedrock과 카탈로그의 MCP endpoint를 불렀다), 이 PC가 모든 주소(`0.0.0.0`)에 연 포트에도 닿을 수 있다(Docker의 기본 동작이고, 여기서 해 보지는 않았다). 이 저장소가 이 PC에 띄우는 허브 화면(`127.0.0.1:8300`)과 두 터미널(`127.0.0.1:7681`, `127.0.0.1:7682`)은 loopback 주소에서만 듣는다. 인스턴스 메타데이터 서비스로 가는 길은 위의 "컨테이너에 들어가는 자격 증명 둘"에 적은 대로 막는다.

### `run.sh`

| 명령 | 하는 일 |
|---|---|
| `run.sh build` | 이미지 `hub-dev-pc`를 만든다. build context 없이 만들므로 이 PC의 파일은 이미지에 들어가지 않는다. |
| `run.sh creds` | 자격 증명 둘을 만들어 파일로 둔다. 컨테이너가 떠 있는 동안 다시 돌려도 된다(파일을 바꿔 두면 컨테이너는 다음 명령부터 새 것을 읽는다). |
| `run.sh up` | 컨테이너를 새로 띄우고 blackhole 경로를 넣는다. 그다음 컨테이너 안에서 작업 폴더를 새로 만들고(아래), `.mcp.json`을 허브의 카탈로그 ID로 채우고, `uv sync`를 한 번 돌린다. 홈(`demo_video/out/dev-pc/home`)은 남는다. 끝에 작업 폴더의 `dev_team/` 목록을 찍는다(제어 문자를 빼고 300자에서 자른다). |
| `run.sh check` | Claude Code의 버전, `claude -p`가 Bedrock으로 답하는지, 인스턴스 메타데이터 서비스에 닿지 않는지, 사용자 `dev`의 권한(`CapEff`)과 경로를 지우지 못하는지, MCP 서버의 도구 목록, 개발팀 역할로 `search`, 셸과 Claude Code의 셸 도구에서 `aws sts get-caller-identity`가 개발팀 역할인지 본다. 컨테이너가 찍은 글은 표준 오류까지 제어 문자를 빼고(탭과 줄바꿈은 남긴다), 계정을 가리고, 한 줄을 300자에서 잘라 보인다. |
| `run.sh term` | ttyd를 `127.0.0.1:7681`에서만 띄운다(`-i lo`). 페이지를 열 때마다 컨테이너에 새 셸이 뜬다. |
| `run.sh agent <에이전트>` | 리포에서 git이 추적하는 `dev_team/<에이전트>`를 그때 컨테이너 안의 `dev_team/`에 넣는다. 그 자리에 있던 것(Claude Code가 만든 것)은 컨테이너 안에서 `/home/dev/made-by-claude/`로 옮겨 둔다. |
| `run.sh stop` | ttyd와 컨테이너를 멈춘다. 홈은 남는다. |
| `run.sh forget` | 자격 증명 파일 둘을 지운다. |
| `run.sh down` | `stop`과 `forget`. |

새 홈(처음이거나 `demo_video/out/dev-pc`를 지운 뒤)에서는 Claude Code 장면을 찍기 전에 `run.sh term`의 터미널에서 `claude`를 한 번 띄워, 처음에만 나오는 화면들(아래 "2026-11-23에 확인한 것"의 넷)에 손으로 답하고 나온다. 답은 홈에 남고, 그 뒤로 `claude`는 곧바로 입력 줄로 시작한다. 스토리보드(`lib/claude.mjs`의 `startClaude`)는 입력 줄의 표시 `❯`가 화면에 나오면 Claude Code가 시작된 것으로 본다. 그런데 2026-11-23의 첫 화면(글자 모양 고르기, 이 폴더를 믿는지 묻는 창)에서는 고른 줄에도 그 표시가 붙었고, 그 줄에 번호가 없어서 스토리보드는 그것을 묻는 창의 선택지 줄로 보지 않는다. 그러니 답하지 않은 홈에서는 그 화면에 요청을 붙여 넣고 Enter를 누를 것이다(코드와 그날의 화면으로 본 것이고, 해 보지 않았다. 이 폴더를 믿는지 묻는 창의 기본 선택은 "No, exit"이다).

### 개발자의 작업 폴더

`/home/dev/work`는 개발자의 checkout이자 Claude Code의 프로젝트 폴더다. 리포에서 git이 추적하는 `dev_team/`, `platform_team/`, `demo_scenes/`, `pyproject.toml`, `uv.lock`(Terraform 상태, `build/`, `.env`는 넣지 않는다)과 이 폴더의 `CLAUDE.md`, `.mcp.json`, `.claude/settings.json`이 들어 있다. `demo_scenes/`가 PATH의 맨 뒤에 있어서 개발자는 `search "…"`, `publish <에이전트>`, `logs <에이전트>`로 친다(작업 폴더의 파일이 `ls`, `cat`, `uv`, `ip`를 가리지 못한다).

영상의 이야기에서 개발자는 Claude Code로 `quality_agent`를 만든다. 그래서 `run.sh up` 뒤의 작업 폴더에는 `dev_team/quality_agent`가 없다. Claude Code가 만든 에이전트는 화면에 보이기만 하고 올리지 않는다. 올리는 것은 리포의 `dev_team/quality_agent`(변형 `v1-vulnerable`, `v2-loop`를 포함한다)다. 뒤의 장면이 그 변형(취약한 라이브러리, 도구를 되풀이해 부르는 판)을 쓰기 때문이다. 만드는 장면과 올리는 장면 사이에 화면 밖에서 `run.sh agent quality_agent`를 돌린다. `run.sh up`을 다시 돌리면 작업 폴더를 새로 만든다. 그때도 작업 폴더 안의 Python 환경(`.venv`)과 컨테이너의 홈(Claude Code의 첫 화면의 답, 메모와 대화 기록, `made-by-claude/`)은 남는다.

### Claude Code가 묻지 않고 하는 일

`settings.json`의 `permissions.allow`에 있는 것뿐이다.

| 규칙 | 묻지 않고 하는 일 |
|---|---|
| `mcp__hub-catalog__*` | 카탈로그 MCP 서버의 도구(검색과 record 읽기) |
| `Edit(./dev_team/**)` | `dev_team/` 아래의 파일 쓰기와 고치기(에이전트를 만드는 곳) |
| `Bash(search:*)`, `Bash(logs:*)` | 카탈로그 검색, 에이전트의 로그 보기(로그 줄은 호스팅된 에이전트의 코드가 쓴 글이다. [`demo_scenes/README.md`](../demo_scenes/README.md)의 `logs`) |
| `Bash(ls:*)`, `Bash(cat:*)` | 작업 폴더의 목록과 파일 보기(그러려고 둔 규칙이다. 규칙 자체에는 경로나 리다이렉트의 제한이 없다. 아래) |

`Bash(ls:*)`와 `Bash(cat:*)`는 명령의 이름만 정하고, 어느 경로를 읽는지나 리다이렉트(`>`)가 붙는지는 정하지 않는다. 2026-11-23에 `claude -p`로 해 본 것은 `cat /etc/hostname` 하나다. 같은 모양의 거부 규칙(`Read(//etc/hostname)`)을 더했을 때 거부되었고(위의 "한계"에 적은 시험), 그 규칙 없이도 Claude Code가 막았다(이 세션에서는 작업 폴더 `/home/dev/work`의 파일만 이어 붙일 수 있다는 문장). 리다이렉트가 붙은 `cat`(`cat … > 파일`)과, 작업 폴더 밖의 다른 경로를 보는 `ls`나 `cat`은 해 보지 않았다.

`permissions.deny`에 있는 것은 묻지 않고 거부한다.

| 규칙 | 까닭 |
|---|---|
| `Read(//run/dev-pc/**)` | 자격 증명 파일 |
| `Edit(./demo_scenes/**)` | 묻지 않고 도는 명령(`search`, `logs`)의 파일 |
| `Edit(./platform_team/**)` | 그 명령이 부르는 허브의 코드 |
| `Edit(./pyproject.toml)`, `Edit(./uv.lock)` | 그 명령이 쓰는 Python 환경 |
| `Edit(./.claude/**)`, `Edit(./.mcp.json)` | Claude Code 자신의 설정과, 묻지 않고 뜨는 MCP 서버 |
| `Edit(./dev_team/.claude/**)`, `Edit(./dev_team/.mcp.json)`, `Edit(./dev_team/CLAUDE.md)` | `dev_team/` 아래는 묻지 않고 쓰는 곳이라서, `dev_team/` 바로 아래에 다음 세션이 읽을 Claude Code의 폴더(스킬, 훅, 설정), MCP 서버 목록, 지시 파일을 만들지 못하게 하려는 규칙이다. 아래 줄의 `**/`가 폴더 없이도 맞는지에 기대지 않으려고 이름으로 적었다. 녹화(2026-11-23) 뒤에 더했고 컨테이너에서 해 보지 않았다 |
| `Edit(./dev_team/**/.claude/**)`, `Edit(./dev_team/**/.mcp.json)`, `Edit(./dev_team/**/CLAUDE.md)` | 같은 셋을 `dev_team/` 아래의 폴더 안에. 2026-11-23에 `dev_team/x/.claude/skills/y/SKILL.md` 하나로 시험했고 거부되었다(아래) |
| `Edit(~/.claude/**)`, `Edit(~/.claude.json)` | 컨테이너의 홈에 있는 Claude Code 자신의 파일(설정, 스킬, 메모, 첫 화면의 답). 홈은 `run.sh up` 뒤에도 남는다. 녹화(2026-11-23) 뒤에 더했고 컨테이너에서 해 보지 않았다 |

장면 명령(`search`, `logs`, `ask`, `publish`)은 Python을 `-I`(격리 모드)로 띄우므로, 명령을 부른 폴더(예: Claude Code가 묻지 않고 쓸 수 있는 `dev_team/` 아래)의 파일을 모듈로 불러오지 않고, 부른 쪽의 `PYTHON…` 환경 변수(`PYTHONPATH`, `PYTHONWARNINGS` 등)도 읽지 않는다. 그 밖의 도구는 Claude Code가 화면에서 묻는다. `publish`도 묻는다(이야기에서 올리는 것은 개발자가 직접 친다). 시험(`uv run pytest`)도 묻는다. 권한을 건너뛰는 모드나 플래그는 쓰지 않는다(`run.sh check`만 `claude -p`에 `--allowedTools "Bash(aws sts get-caller-identity --query Arn --output text)"`를 준다. 그 한 명령이 개발팀 역할로 도는지 보는 것이다). Claude Code 2.1.330은 따로 정하지 않으면 auto mode(Claude가 도구 호출의 위험을 스스로 판단해 낮다고 본 것은 묻지 않고 실행한다)로 시작하므로(2026-11-23에 컨테이너에서 처음 띄웠을 때 그렇게 알렸다), 설정이 묻는 모드를 정하고(`"defaultMode": "default"`) auto mode를 끈다(`"disableAutoMode": "disable"`. Claude Code의 settings reference는 이 키가 auto mode를 `Shift+Tab`의 순환에서 빼고, auto mode로 시작했을 세션을 `default`로 시작하게 한다고 적는다. 2026-11-23에 읽었다). `.mcp.json`의 서버는 `enabledMcpjsonServers`로 승인해 둔다.

2026-11-23에 이 설정으로 컨테이너에서 본 것이다(`claude -p`로). MCP 검색 도구는 묻지 않고 돌았다. `demo_scenes/search`를 고쳐 달라는 요청은 Claude Code가 스스로 거절했고, 편집 도구로 한 번 시도해 보라고 하자 그 도구가 `File is in a directory that is denied by your permission settings.`로 거부했다(파일은 바뀌지 않았다). `logs docs_adk 60`은 묻지 않고 돌았다. Claude Code가 `dev_team/x/json.py`(불러오면 표시 파일을 쓰는 두 줄)를 묻지 않고 쓰고 그 폴더에서 `search`를 묻지 않고 돌렸을 때, `search`는 여느 때의 줄을 찍었고 그 파일은 실행되지 않았다. `PYTHONPATH=dev_team/x search …`와 작업 폴더 맨 위에 파일을 쓰는 것(`sitecustomize.py`)은 묻는 일이어서 `claude -p`에서 거절되었다. 장면 명령을 `-I`로 바꾸고 `dev_team/` 아래의 폴더 안의 거부 셋(`Edit(./dev_team/**/…)`)을 더한 뒤(11:42 UTC), 컨테이너에서 네 장면 명령은 다른 폴더에서 불러도 잘못된 사용에 종료 값 2로 멈췄고 `search "part specification tool"`은 여느 때의 줄을 찍었다. 부른 쪽의 `PYTHONPATH`와 `PYTHONWARNINGS`가 가리킨 `dev_team/x/planted.py`는 불러오지 않았다. `dev_team/x/.claude/skills/y/SKILL.md`를 쓰라는 요청에는 Claude Code의 쓰기 도구가 `File is in a directory that is denied by your permission settings.`로 거부되었고, 파일은 생기지 않았다(`claude -p`). ttyd의 대화형 세션에서 Claude Code가 물을 때 고를 수 있는 것은 `Yes`, `Yes, and don't ask again for: …`, `No`였고, auto mode로 바꾸는 선택지는 없었다. `Shift+Tab`은 manual, accept edits, plan 사이만 돌았다.

### 2026-11-23에 확인한 것

시각은 UTC다. 허브는 09:58:51에 `make deploy seed preload`를 시작했고, `make preload`는 10:13:50에 끝났다. 그래서 첫 `run.sh up`(10:06)과 첫 `run.sh check`(10:07), Claude Code의 첫 화면들(10:09), 아래 세 가지를 한 Claude Code 세션(10:10~10:13)은 `make deploy`와 `make seed`가 끝나고 `make preload`가 아직 돌 때다. 그때 `spec_assistant`는 승인되어 검색에 나왔고, `docs_adk`는 심사 중이었다. `logs` 명령(10:14)과 두 번째 `run.sh check`(10:16)는 `make preload`가 끝난 뒤다(`parts-tools`, `spec_assistant`, `docs_adk`가 승인되어 있었다).

- 첫 `run.sh check`(20초)는 모두 통과했다. 그때는 아직 이 폴더를 믿는다는 답이 없어서 Claude Code가 "Ignoring 9 permissions.allow entries ... this workspace has not been trusted"를 두 번 찍었다. 두 번째 `run.sh check`(19초)는 그 줄 없이 모두 통과했다. 둘 다 `claude -p`가 4~5초에 답했다. 개발팀 역할에는 Bedrock 권한이 없으므로 그 답은 Bedrock 토큰으로 온 것이다. 인스턴스 메타데이터 서비스는 답하지 않았다. MCP 서버는 개발팀 역할로 도구 넷(`search_discoverable_registry_records`, `search_discoverable_registry_records_paginated`, `list_discoverable_registry_records`, `batch_get_discoverable_registry_record`)을 보였다. `search "part specification tool"`은 `parts-tools`(도구 둘과 그 입력 필드)와 `spec_assistant`를 찍었다. `aws sts get-caller-identity`는 셸에서도, Claude Code의 셸 도구에서도 `assumed-role/hub-dev-role/developer`였다. `awsCredentialExport`의 토큰은 Claude Code의 모델 호출에만 쓰였고 Claude Code가 띄운 도구에는 넘어가지 않았다. 같은 날 지금의 `run.sh`로 돌린 `run.sh check`(19초)도 모두 통과했고, `CapEff:	0000000000000000`과 `RTNETLINK answers: Operation not permitted`를 찍었다.
- `run.sh creds`를 컨테이너가 떠 있는 동안 다시 돌리자, 컨테이너 안에서 본 두 파일의 inode와 수정 시각이 곧바로 이 PC의 새 파일과 같아졌고, 다음 명령(`aws sts get-caller-identity`)이 개발팀 역할로 답했다. `run.sh up`은 3~4초였다(`uv sync` 포함).
- Claude Code를 처음 띄웠을 때 나온 화면은 넷이었다. 글자 모양(theme) 고르기(Dark mode를 골랐다), 보안 안내(Enter), 이 폴더를 믿는지 묻는 창(설정이 미리 허락한 권한을 보이고 기본 선택은 "No, exit"이다. "Yes, I trust this folder"를 골랐다), 그리고 auto mode가 기본 권한 모드가 되었다는 알림이다. 답은 홈의 `~/.claude.json`과 `~/.claude/settings.json`에 남았고, 그 뒤로 `claude`는 2초 남짓에 곧바로 입력 줄로 시작했다. 머리에는 `Claude Code v2.1.330`, `Sonnet 5.5 · Amazon Bedrock`, `~/work`가 나왔고 조직, 이메일, 계정은 나오지 않았다. 처음 띄울 때 Claude Code는 공식 플러그인 마켓플레이스(`anthropics/claude-plugins-official`, GitHub)를 등록해 두었다(`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`인데도. 홈의 `known_marketplaces.json`에 10:09에 받은 것으로 남아 있다). 설치된 플러그인은 없었다.
- 카탈로그 검색: "부품 규격을 읽어 오는 도구가 필요합니다. 허브에 그런 도구가 있나요?"라고 묻자 Claude Code는 셸 명령 `search`를 골랐다. `search "부품 규격"`에는 맞는 record가 없었고, 한 명령으로 돌린 `search "part specification"; search "datasheet"; search "spec"; search "부품"` 가운데 `"part specification"`이 `spec_assistant`와 `parts-tools`를 찾았다(나머지 셋은 맞는 record가 없었다. 13초). "카탈로그 MCP 서버(hub-catalog)로 부품 규격을 읽는 도구를 찾아서, 그 도구의 record를 보여 주세요."라고 하자 MCP 도구 `search_discoverable_registry_records`(검색어 `part specification read tool`)를 불러 `parts-tools`의 record(버전, 설명, Target `Parts`, 도구 둘과 입력 필드)를 보였다(7초). 두 번 다 권한을 묻지 않았다. 이때의 설정은 지금의 것보다 넓었다(작업 폴더 전체의 고치기, `publish`, `uv run pytest`도 묻지 않았다).
- 에이전트 만들기: 같은 세션에서 "템플릿으로 검사 결과와 부품 규격에 답하는 에이전트 quality_agent를 Strands로 만들어 주세요. 도구는 방금 찾은 Parts___get_part_spec을 쓰세요. 파일만 만들고 올리지는 마세요."라고 하자 `dev_team/quality_agent/`에 다섯 파일(템플릿 그대로의 `main.py`와 `hub_tools.py`, `agent.json`, `requirements.txt`, Strands로 쓴 `agent.py`)을 만들었고 올리지 않았다. 그동안 Claude Code는 여섯 번 물었다(화면을 보며 센 것이고, 다섯 번의 화면을 남겼다). `for` 문으로 템플릿과 예시 에이전트의 파일을 읽는 셸 명령 둘, PyPI에서 `strands-agents`의 버전을 찾는 `pip` 명령(거절하고 "패키지 버전은 이 폴더의 uv.lock에 있는 것을 쓰고, 계속 만들어 주세요."라고 답했다), `cd`와 상대 경로의 `find`(Read의 `deny`가 있으면 묻는다), 폴더를 만들고 템플릿을 복사하는 `mkdir`와 `cp`, `requirements.txt`에 줄을 더하는 `echo >>`다. 파일 쓰기와 `grep`은 묻지 않았다. 컨테이너에 `python3` 명령이 없어서, Claude Code는 만든 코드의 문법을 확인하지 못했다고 말했다. 이것도 지금보다 넓은 설정에서였다. 지금의 설정에서는 `dev_team/` 밖의 파일 쓰기도 묻는다.
