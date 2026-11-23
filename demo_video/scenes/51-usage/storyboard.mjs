// 51-usage (stage 5): the agents page: the hosted agents with their usage of the last hour (calls, sessions, errors,
// vCPU and memory hours), the calls of each tool, and the tool-call alarm with its threshold (OK). Changes nothing.
import { openPage } from '../lib/hub.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['hub'];

export default async function storyboard({ page, rec, option }) {
  await needState({ records: { release_review: 'APPROVED', docs_adk: 'APPROVED', quality_agent: 'APPROVED' },
    reviewing: [], stopped: [] });
  texts(option);
  const cam = kit({ page, rec, option });

  await openPage(page, rec, '/agents');
  await cam.reset('wide', 'the hosted agents and the tool-call alarm');
  await cam.hold(5000);
  await cam.focus('agents', '#panel-agents', { pad: 16, kmax: 1.5 }, 'each agent\'s usage of the last hour');
  await cam.hold(8000);
  await cam.focus('tools', '#panel-tools', { pad: 16, kmax: 1.6 }, 'the calls of each tool');
  await cam.hold(6000);
  await cam.focus('alarm', '#panel-alarm', { pad: 16, kmax: 1.5 }, 'the tool-call alarm and its threshold');
  await cam.hold(7000);
}
