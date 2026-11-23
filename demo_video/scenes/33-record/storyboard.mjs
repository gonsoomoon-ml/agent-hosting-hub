// 33-record (stage 3): the policy page's log-only report: the request of 32-passes is counted for release_review (a
// match, and a request the policy would have blocked), none for the other agents. The report reads a CloudWatch
// metric that arrives about a minute after the request: the take waits on the page (a note when the match shows), up
// to 180 s. Changes nothing.
import { openPage } from '../lib/hub.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';
import { PROMPT_CARD, report } from '../lib/policies.mjs';

export const surfaces = ['hub'];

export default async function storyboard({ page, rec, option, maxSeconds }) {
  await needState({ records: { release_review: 'APPROVED' }, mode: 'LOG_ONLY', stopped: [] });
  texts(option);
  const cam = kit({ page, rec, option });

  await openPage(page, rec, '/policies');
  await cam.focus('logonly', PROMPT_CARD, { pad: 16, kmax: 1.9 }, 'guard_prompt in log-only mode');
  await cam.hold(5000);
  const frame = () => cam.focus('report', '#panel-report', { pad: 16, kmax: 1.9 }, 'what the policy matched, per agent');
  await frame();
  let last = JSON.stringify(await report(page)), counted = false;
  const t0 = rec.now();
  while (rec.now() - t0 < Math.min(180, maxSeconds - 30)) {
    await cam.hold(1000);
    const now = await report(page);
    if (JSON.stringify(now) !== last) { last = JSON.stringify(now); await frame(); }
    if ((now.release_review?.matches ?? 0) >= 1) { counted = true; rec.note('match_counted', { report: now }); break; }
  }
  if (!counted) rec.note('no_match_in_time', { report: JSON.parse(last) });
  await cam.hold(1500);
  await frame();
  await cam.hold(8000);
}
