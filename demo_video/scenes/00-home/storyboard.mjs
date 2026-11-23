// 00-home (stage 0, the preparation): the hub screen's home. The two flow pictures, what the platform team built once (the platform's parts
// and the AWS service of each), the counts, and the catalog with the agents that are there. Changes nothing.
import { openPage } from '../lib/hub.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['hub'];

export default async function storyboard({ page, rec, option }) {
  await needState({ records: { docs_adk: 'APPROVED', spec_assistant: 'APPROVED', 'parts-tools': 'APPROVED',
    quality_agent: 'absent', release_review: 'absent' }, reviewing: [], mode: null, attached: false, stopped: [] });
  texts(option);
  const cam = kit({ page, rec, option });
  await openPage(page, rec, '/');

  await cam.reset('wide', 'the home: counts, the two flows, the platform');
  await cam.hold(6000);
  await cam.focus('counts', '#panel-counts', { pad: 16, kmax: 1.6 }, 'hosted agents, awaiting approval, tools');
  await cam.hold(5000);
  // flow 1 framed from the content's left edge, so the menu stays out of the frame
  // (in page coordinates: the camera's rect undoes its own zoom)
  const fig = await page.evaluate(() => window.__cam.rect('#pictures figure.p1'));
  await cam.region('flow1', fig.x - 66, fig.y - 8, 1024, fig.h + 16, { pad: 0, kmax: 1.9 }, 'flow 1: hosting');
  await cam.hold(7000);
  await cam.focus('flow2', '#pictures figure.p2', { pad: 12, kmax: 1.9 }, 'flow 2: operations');
  await cam.hold(7000);
  await cam.focus('platform', '#panel-platform', { pad: 16, kmax: 1.9 }, 'what the platform team built once');
  await cam.hold(7000);
  await cam.focus('catalog', '#panel-catalog', { pad: 16, kmax: 1.7 }, 'the catalog: the agents and the shared tool');
  await cam.hold(6000);
  await cam.reset('end');
  await cam.hold(2500);
}
