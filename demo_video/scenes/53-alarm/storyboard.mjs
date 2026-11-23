// 53-alarm (stage 5): the agents page while quality_agent's loop runs: the bars of the watched tool's calls per minute
// rise past the threshold and the alarm's state turns to ALARM. Real time, with a note when the first bar crosses the
// threshold and when the state changes; it waits up to 420 s (the cut speeds this wait up). Changes nothing. Started
// during 52-incident, right after its incident call.
import { openPage } from '../lib/hub.mjs';
import { needState } from '../lib/state.mjs';
import { kit } from '../lib/take.mjs';
import { texts } from '../lib/texts.mjs';

export const surfaces = ['hub'];

/** The alarm as the page draws it: its state and the bars ({ value, over }). */
async function alarm(page) {
  return page.evaluate(() => ({
    state: document.querySelector('#panel-alarm .pill.big')?.textContent.trim() || '',
    bars: [...document.querySelectorAll('#panel-alarm svg.bars text.val')].map(v => ({
      value: Number(v.textContent.replace('▲', '').trim()), over: v.classList.contains('over') })),
  })).catch(() => ({ state: '', bars: [] }));
}

export default async function storyboard({ page, rec, option, maxSeconds }) {
  await needState({ records: { quality_agent: 'APPROVED' }, stopped: [] });
  texts(option);
  const cam = kit({ page, rec, option });

  await openPage(page, rec, '/agents');
  const frame = () => cam.focus('alarm', '#panel-alarm', { pad: 16, kmax: 1.5 }, 'the tool-call alarm');
  await frame();
  let last = await alarm(page), crossed = last.bars.some(b => b.over), fired = last.state === 'ALARM';
  rec.note(`state_${last.state || 'none'}`, { bars: last.bars.map(b => b.value) });
  const t0 = rec.now();
  while (!fired && rec.now() - t0 < Math.min(420, maxSeconds - 30)) {
    await cam.hold(1000);
    const now = await alarm(page);
    if (JSON.stringify(now.bars) !== JSON.stringify(last.bars)) rec.note('bars', { bars: now.bars.map(b => b.value) });
    if (!crossed && now.bars.some(b => b.over)) { crossed = true; rec.note('first_bar_over'); await frame(); }
    if (now.state && now.state !== last.state) { rec.note(`state_${now.state}`); await frame(); }
    if (now.state === 'ALARM') fired = true;
    last = now;
  }
  if (!fired) rec.note('no_alarm_in_time', { state: last.state, bars: last.bars.map(b => b.value) });
  await cam.hold(2000);
  await cam.focus('bars', '#panel-alarm svg.bars', { pad: 12, kmax: 1.8 }, 'the calls per minute over the threshold');
  await cam.hold(6000);
  await frame();
  await cam.hold(6000);
}
