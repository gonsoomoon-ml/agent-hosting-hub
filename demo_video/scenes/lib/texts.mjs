// Every text a take types or waits for, by language (record.sh passes --lang; only ko is recorded). An English
// version needs new takes only where these texts show on the frame.
export const TEXTS = {
  ko: {
    // who types: the prompt of the developer PC (its /etc/bash.bashrc) and of the user's shell (user_shell.sh)
    prompt: { dev: '개발자 $', user: '사용자 $' },
    // 11-find and 12-make: the developer's two requests to Claude Code, in one session
    find: '카탈로그 MCP 서버(hub-catalog)에서 부품 번호로 부품 규격을 돌려주는 사내 도구를 찾아서, 그 도구의 이름과 설명, 입력을 보여 주세요.',
    make: '표준 템플릿(dev_team/agent_template)으로 에이전트 quality_agent를 Strands로 만들어 주세요. 부품 규격을 묻는 질문에 '
      + '방금 찾은 도구로 답하는 에이전트입니다. 패키지 버전은 이 폴더의 uv.lock에 있는 것을 쓰세요. 파일만 만들고, '
      + '실행하거나 올리지는 마세요.',
    // the developer's answer when Claude Code asks to run code or to publish (answered No)
    noRun: '실행하거나 올리지 말고 파일만 만들어 주세요.',
    // 23-reject: the platform engineer's reason
    reject: 'jinja2 2.11.2에 알려진 취약점이 있어 반려합니다. 이 의존성을 빼거나 취약점이 고쳐진 버전으로 올린 뒤 다시 신청해 주세요.',
    // 56-cause: the developer's request to Claude Code (it names what was published, not the cause)
    cause: 'publish quality_agent v2-loop로 올린 quality_agent가 검사 Q-1002 질문에 답하지 않고 같은 도구를 계속 불렀습니다. '
      + 'logs quality_agent 30으로 최근 로그를 읽고, dev_team/quality_agent의 코드(올린 것은 v2-loop 판)를 읽어서 왜 그랬는지 '
      + '찾아 주세요. 파일을 고치거나 다른 명령을 돌리지는 마세요.',
    // 56-cause: the developer's answer when Claude Code asks to run something (answered No)
    readOnly: '다른 명령은 돌리지 말고, logs와 cat, 읽기 도구로만 읽어 주세요.',
  },
};

/** The texts of the take's language (the storyboard's --lang option, ko when absent). */
export function texts(option) {
  const lang = option('--lang', 'ko');
  const t = TEXTS[lang];
  if (!t) throw new Error(`no texts for the language '${lang}' (there are: ${Object.keys(TEXTS).join(', ')})`);
  return t;
}
