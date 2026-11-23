// 25-approved (stage 2): the hosting review of quality_agent's fixed version, in real time: every step passes and the
// record reads APPROVED. A note at every change. Record it right after 24-again, with 720 s.
import { openPage, stepChanges, waitForReview } from '../lib/hub.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['hub'];

export default async function storyboard({ page, rec, option, maxSeconds }) {
  const s = await needState({ records: { quality_agent: 'PENDING_APPROVAL', release_review: 'APPROVED' },
    mode: null, attached: false, stopped: [] });
  if (!s.reviewing.includes('quality_agent')) throw new Error('state: the review of quality_agent is not running');
  texts(option);
  const cam = kit({ page, rec, option });
  const seen = {};

  await openPage(page, rec, '/reviews/quality_agent');
  await cam.reset('wide', 'the fixed version under review');
  await stepChanges(page, rec, seen, '#panel-steps', 'quality_agent_');
  await cam.hold(5000);
  await cam.focus('steps', '#panel-steps', { pad: 12, kmax: 1.7 }, 'the seven steps and their AWS services');
  const review = await waitForReview(page, rec, cam, { until: maxSeconds - 40, prefix: 'quality_agent_', seen });
  if (!review.approved) rec.note('not_approved_in_time');
  await cam.hold(1500);
  await cam.focus('record', '#panel-application .app-facts', { pad: 16, kmax: 2.0 }, 'the record reads APPROVED');
  await cam.hold(5000);
  await cam.focus('steps_done', '#panel-steps', { pad: 12, kmax: 1.7 }, 'every step passed');
  await cam.hold(7000);
}
