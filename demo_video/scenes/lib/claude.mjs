// Claude Code in the developer PC, driven like a person at the keyboard. What it prints is untrusted: the text of a
// permission question is chosen by another agent, so the storyboard does not judge it. It never answers Yes: when
// Claude Code asks, the storyboard frames the question, holds it for the camera and presses Escape (No), then sends
// the take's sentence that says how to go on. The only key it sends while a question is on the screen is Escape;
// Enter is pressed only to send a pasted request, after a look that finds no option row anywhere on the screen.
import { term } from './plugin.mjs';

const BUSY = 'esc to interrupt';
const ASKS = 'Do you want to';
// an option row of a dialog ("❯ 1. Yes", "  2. No", "  2. Yes, and don't ask again …"): seeing one anywhere on the
// screen forbids Enter, also when it is only text in an answer
const OPTION = /^\s*(❯\s*)?\d\.\s+(Yes|No)\b/;
const TITLES = { 'Bash command': 'shell', 'Create file': 'file', 'Edit file': 'file', 'Write file': 'file' };

export async function rows(page) { return (await term.screenText(page)).split('\n').map(r => r.replace(/\s+$/, '')); }

/** Whether any row of the screen looks like an option of a dialog. */
export const optionOnScreen = r => r.some(l => OPTION.test(l));

/** The question on the screen, or null: the last row that asks ("Do you want to") and is followed, past blank rows,
 * by an option row "1. …". A row that only resembles a question (in Claude Code's answer) is not one. For the camera
 * and the notes: the rows to frame [top, end] and the kind (shell, file, or unknown, from the title above). */
export function question(r) {
  for (let k = r.length - 1; k >= 0; k--) {
    if (!r[k].includes(ASKS)) continue;
    let n = k + 1;
    while (n < r.length && !r[n].trim()) n++;
    if (n >= r.length || !/^\s*(❯\s*)?1\.\s/.test(r[n])) continue;
    let end = n;
    while (end + 1 < r.length && (OPTION.test(r[end + 1]) || /^ {6}\S/.test(r[end + 1]))) end++;
    let top = Math.max(0, k - 10), kind = 'unknown';
    for (let j = k - 1; j >= 0; j--) {
      const title = TITLES[r[j].trim()];
      if (title) { kind = title; top = j > 0 && /^─{8,}$/.test(r[j - 1]) ? j - 1 : j; break; }
    }
    return { row: k, top, end, kind, text: r[k].trim() };
  }
  return null;
}

/** Press Enter to send what was pasted, only when no option row is on the screen: when one is, press Escape and look
 * again, and stop the take with one line when it is still there. */
async function send(page, look) {
  if (optionOnScreen(await look())) {
    await page.keyboard.press('Escape');
    await page.waitForTimeout(1500);
    const again = await look();
    if (optionOnScreen(again)) {
      throw new Error(`an option row stays on the screen, so Enter is not pressed: ${again.find(l => OPTION.test(l)).trim()}`);
    }
  }
  await page.keyboard.press('Enter');
}

/** Start Claude Code from the shell and wait for its input prompt. */
export async function startClaude(page) {
  await term.type(page, 'claude', 60);
  await page.waitForTimeout(400);
  await send(page, () => rows(page));
  if (!(await term.waitPrompt(page, 30000))) throw new Error('Claude Code did not show its prompt within 30 s');
  await page.waitForTimeout(1500);
}

/** Send one request (pasted: Korean survives) and follow Claude Code until it is done. Every screen not seen before
 * is kept for the take's text check (cam.keep). Each permission question is framed, held for the camera and answered
 * No (Escape); then `noRun` is sent as the way to go on. Returns { prompts: [{ question, kind, answer: 'no' }],
 * seconds }. */
export async function request(page, rec, cam, text, { noRun, limitMs = 600000, idleMs = 3000 } = {}) {
  const seen = new Set();
  const look = async () => {
    const r = await rows(page);
    const screen = r.join('\n');
    if (!seen.has(screen)) { seen.add(screen); cam.keep(screen); }
    return r;
  };
  await term.paste(page, text);
  await page.waitForTimeout(1200);
  await send(page, look);
  const t0 = Date.now();
  const prompts = [];
  let busy = false, lastBusy = 0;
  while (Date.now() - t0 < limitMs) {
    const r = await look();
    const q = question(r);
    if (q) {
      rec.note('permission', { answer: 'no', kind: q.kind });
      await cam.lines(`ask${prompts.length + 1}`, q.top, q.end, { pad: 24, kmax: 1.5 }, `permission question ${prompts.length + 1}`);
      await cam.hold(4500);
      await page.keyboard.press('Escape');
      await page.waitForTimeout(1500);
      if (noRun) { await term.paste(page, noRun); await page.waitForTimeout(800); await send(page, look); }
      prompts.push({ question: q.text, kind: q.kind, answer: 'no' });
      await page.waitForTimeout(1500);
      await cam.reset(`work${prompts.length}`);
      busy = true; lastBusy = Date.now();
      continue;
    }
    if (r.join('\n').includes(BUSY)) { busy = true; lastBusy = Date.now(); }
    else if (busy && Date.now() - lastBusy >= idleMs) return { prompts, seconds: (Date.now() - t0) / 1000 };
    await page.waitForTimeout(400);
  }
  throw new Error(`Claude Code did not finish within ${limitMs / 1000} s`);
}

/** The rows of Claude Code's last answer: from the row of the request (or a marker) to the row above its input box. */
export function answerRows(r, fromNeedle) {
  let box = r.length - 1;
  for (let k = r.length - 1; k >= 0; k--) { if (r[k].includes('❯')) { box = k; break; } }
  let end = box - 1;
  while (end > 0 && (/^\s*[─━]+\s*$/.test(r[end]) || !r[end].trim())) end--;
  let start = -1;
  for (let k = end; k >= 0; k--) { if (r[k].includes(fromNeedle)) { start = k; break; } }
  return start < 0 ? null : [start, end];
}
