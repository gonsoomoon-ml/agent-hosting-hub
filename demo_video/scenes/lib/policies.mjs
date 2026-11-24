// The policy page of the hub screen (/policies): the card of the company policy guard_prompt, the log-only report and
// the policy rows of the agent gateway.

/** The card of guard_prompt (its mode and its three buttons): the second card of the company policies. */
export const PROMPT_CARD = '#panel-company article.policy:last-child';

/** Frame the agent gateway's policy rows whose names start with `prefix` (the rows around them show too: the frame is
 * as wide as the table), or the whole table when there is none. */
export async function policyRows(page, cam, key, prefix, label) {
  const r = await page.evaluate(start => {
    const table = '#panel-gateway-agent_gw tbody tr';
    const hit = [...document.querySelectorAll(table)].map((tr, i) => (tr.querySelector('.name')?.textContent.trim()
      .startsWith(start) ? i + 1 : 0)).filter(Boolean);
    if (!hit.length) return null;
    const first = window.__cam.rect(`${table}:nth-child(${hit[0]})`);
    const last = window.__cam.rect(`${table}:nth-child(${hit[hit.length - 1]})`);
    return { x: first.x, y: first.y, w: first.w, h: last.y + last.h - first.y };
  }, prefix);
  if (!r) return cam.focus(key, '#panel-gateway-agent_gw', { pad: 12, kmax: 1.4 }, label);
  return cam.region(key, r.x, r.y, r.w, r.h, { pad: 16, kmax: 1.6 }, label);
}

/** The log-only report as the page draws it: { <agent>: { mode, matches, flips } } (numbers; {} when it has no rows). */
export async function report(page) {
  return page.evaluate(() => Object.fromEntries([...document.querySelectorAll('#panel-report tbody tr')].map(tr => {
    const td = tr.querySelectorAll('td');
    return [td[0].textContent.trim(), { mode: td[1].textContent.trim(), matches: Number(td[2].textContent.trim()),
      flips: Number(td[3].textContent.trim()) }];
  }))).catch(() => ({}));
}
