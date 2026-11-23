// 11-find and 12-make (stage 1), one Claude Code session in one recording: the developer asks for an in-house tool that
// returns a part's specification (Claude Code calls the catalog's MCP search tool and shows the record that came
// back), then, in the same session, asks for quality_agent made from the standard template with that tool (the note
// make_asked marks where 12-make starts). Files only: nothing is run or published. Changes nothing in the hub.
import { answerRows, request, rows, startClaude } from '../lib/claude.mjs';
import { openShell } from '../lib/shell.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['dev'];

export default async function storyboard({ page, rec, option }) {
  await needState({ records: { 'parts-tools': 'APPROVED', quality_agent: 'absent', release_review: 'absent' },
    reviewing: [], stopped: [] });
  const t = texts(option);
  const cam = kit({ page, rec, option });
  await openShell(page, rec, 'dev', t);

  await cam.reset('shell', 'the developer PC');
  await cam.hold(2500);
  await startClaude(page);
  rec.note('claude_ready');
  await cam.reset('claude', 'Claude Code on Amazon Bedrock');
  await cam.hold(4000);

  // 11-find: the catalog's MCP search tool
  rec.note('find_asked');
  const find = await request(page, rec, cam, t.find, { noRun: t.noRun, limitMs: 240000 });
  rec.note('find_done', { seconds: find.seconds, prompts: find.prompts.length });
  let r = await rows(page);
  const found = answerRowsFrom(r, t.find.slice(0, 12));
  if (found) await cam.lines('record', found[0], found[1], { pad: 24, kmax: 1.4 }, 'the record the catalog returned');
  else await cam.reset('record', 'the record the catalog returned');
  await cam.hold(9000);
  await cam.reset('find_end');
  await cam.hold(2000);

  // 12-make: the agent from the standard template, files only
  rec.note('make_asked');
  const make = await request(page, rec, cam, t.make, { noRun: t.noRun, limitMs: 480000 });
  rec.note('make_done', { seconds: make.seconds, prompts: make.prompts.length });
  r = await rows(page);
  const made = answerRowsFrom(r, t.make.slice(0, 12));
  if (made) await cam.lines('made', made[0], made[1], { pad: 24, kmax: 1.4 }, 'the agent files Claude Code made');
  else await cam.reset('made', 'the agent files Claude Code made');
  await cam.hold(9000);
  await cam.reset('end');
  await cam.hold(2000);
}

/** The rows from the last answer's first row after the request (the request's own row is skipped) to the row above
 * the input box; the answer may begin above the screen, then it starts at the top row. */
function answerRowsFrom(r, requestStart) {
  const span = answerRows(r, requestStart);
  if (span) return [Math.min(span[0] + 1, span[1]), span[1]];
  const top = answerRows(r, '');
  return top ? [0, top[1]] : null;
}
