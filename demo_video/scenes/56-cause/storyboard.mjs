// 56-cause (stage 5), Claude Code in the developer PC: the developer asks why quality_agent kept calling the same tool.
// Claude Code reads the agent's log lines (logs) and its code under dev_team/quality_agent (the v2-loop version is
// what ran) and says what it finds; it is not told the cause. Reading only: logs, cat and Claude Code's reading tools
// ask nothing; any question is answered No with the sentence that points it back to them. Changes nothing.
import { answerRows, request, rows, startClaude } from '../lib/claude.mjs';
import { openShell } from '../lib/shell.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['dev'];

export default async function storyboard({ page, rec, option }) {
  await needState({ records: { quality_agent: 'APPROVED' }, reviewing: [], stopped: ['quality_agent'] });
  const t = texts(option);
  const cam = kit({ page, rec, option });
  await openShell(page, rec, 'dev', t, { check: 'test -f dev_team/quality_agent/variants/v2-loop/agent.py' });

  await cam.reset('shell', 'the developer PC');
  await cam.hold(2500);
  await startClaude(page);
  rec.note('claude_ready');
  await cam.reset('claude', 'Claude Code on Amazon Bedrock');
  await cam.hold(4000);

  rec.note('cause_asked');
  const cause = await request(page, rec, cam, t.cause, { noRun: t.readOnly, limitMs: 480000 });
  rec.note('cause_done', { seconds: cause.seconds, prompts: cause.prompts.length });
  const found = answerRowsFrom(await rows(page), t.cause.slice(0, 12));
  if (found) await cam.lines('cause', found[0], found[1], { pad: 24, kmax: 1.4 }, 'the cause Claude Code found');
  else await cam.reset('cause', 'the cause Claude Code found');
  await cam.hold(12000);
  await cam.reset('end');
  await cam.hold(2000);
}

/** The rows from the answer's first row after the request (the request's own row is skipped) to the row above the
 * input box; when the answer begins above the screen, from the top row. */
function answerRowsFrom(r, requestStart) {
  const span = answerRows(r, requestStart);
  if (span) return [Math.min(span[0] + 1, span[1]), span[1]];
  const top = answerRows(r, '');
  return top ? [0, top[1]] : null;
}
