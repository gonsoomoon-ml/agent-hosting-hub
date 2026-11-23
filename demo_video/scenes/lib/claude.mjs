// Claude Code in the developer PC, driven like a person at the keyboard. What it prints is untrusted: the text of a
// permission question is chosen by another agent, so the storyboard does not judge it. It never answers Yes: when
// Claude Code asks, the storyboard frames the question, holds it for the camera and presses Escape (No), then sends
// the take's sentence that says how to go on. The only key it sends while a dialog is on the screen is Escape; text
// is pasted, and Enter pressed (to send what was pasted, or to start claude at the shell), only after a look that
// finds no option row of a dialog anywhere on the screen.
import { term } from './plugin.mjs';

const BUSY = 'esc to interrupt';
const ASKS = 'Do you want to';
// The option rows of a dialog: a marked numbered row, whatever its text ("❯ 1. Yes", and the options of a question
// Claude Code draws itself, whose texts the other agent writes), and an unmarked numbered row that reads Yes or No
// ("  2. No", "  2. Yes, and don't ask again …"). A plain numbered list in an answer (no marker, other text) is not one.
const MARKED = /^\s*❯\s*\d+\.\s/;
const YES_NO = /^\s*\d+\.\s+(Yes|No)\b/;
const NUMBERED = /^\s*(❯\s*)?\d+\.\s/;
const TITLES = { 'Bash command': 'shell', 'Create file': 'file', 'Edit file': 'file', 'Write file': 'file' };

export async function rows(page) { return (await term.screenText(page)).split('\n').map(r => r.replace(/\s+$/, '')); }

/** Whether a row is an option row of a dialog (the one test for it, used by question() and before every paste and
 * Enter). */
export const isOption = l => MARKED.test(l) || YES_NO.test(l);

/** Whether any row of the screen is an option row of a dialog. */
export const optionOnScreen = r => r.some(isOption);

/** The dialog on the screen, or null: found from its option rows (the last option row on the screen, then up to the
 * dialog's first option), then a few rows upward for the asking row ("Do you want to", which may wrap over two rows);
 * a dialog without one (a question Claude Code draws itself) is still a dialog, its text the row above the options.
 * For the camera and the notes: the rows to frame [top, end] and the kind (shell, file, or unknown, from the title
 * above). */
export function question(r) {
  let n = -1;
  for (let k = r.length - 1; k >= 0; k--) if (isOption(r[k])) { n = k; break; }
  if (n < 0) return null;
  while (n > 0 && !/^\s*(❯\s*)?1\.\s/.test(r[n]) && (NUMBERED.test(r[n - 1]) || /^ {4,}\S/.test(r[n - 1]))) n--;
  let end = n;
  while (end + 1 < r.length && (NUMBERED.test(r[end + 1]) || /^ {4,}\S/.test(r[end + 1]))) end++;
  let row = -1, seen = 0;
  for (let j = n - 1; j >= 0 && seen < 4; j--) {
    if (!r[j].trim()) continue;
    seen++;
    if (r[j].includes(ASKS)) { row = j; break; }
  }
  if (row < 0) { row = n - 1; while (row > 0 && !r[row].trim()) row--; }
  row = Math.max(row, 0);
  let top = Math.max(0, row - 10), kind = 'unknown';
  for (let j = row - 1; j >= 0; j--) {
    const title = TITLES[r[j].trim()];
    if (title) { kind = title; top = j > 0 && /^─{8,}$/.test(r[j - 1]) ? j - 1 : j; break; }
  }
  const text = r.slice(row, n).map(l => l.trim()).filter(Boolean).join(' ');
  return { row, top, end, kind, text };
}

/** Look at the screen before text is pasted or Enter pressed: when an option row of a dialog is on it, press Escape
 * and look again, and stop the take with one line when it is still there. */
async function clear(page, look) {
  if (!optionOnScreen(await look())) return;
  await page.keyboard.press('Escape');
  await page.waitForTimeout(1500);
  const again = await look();
  if (optionOnScreen(again)) {
    throw new Error(`an option row stays on the screen, so nothing is pasted or sent: ${again.find(isOption).trim()}`);
  }
}

/** Press Enter (to send what was pasted, or to start claude at the shell) after a look that finds no dialog. */
async function send(page, look) {
  await clear(page, look);
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
 * is kept for the take's text check (cam.keep). Each dialog is framed, held for the camera and answered No (Escape);
 * then `noRun` is sent as the way to go on (note `permission` { answer: 'no', dialog }). Returns
 * { prompts: [{ question, kind, answer: 'no' }], seconds }. */
export async function request(page, rec, cam, text, { noRun, limitMs = 600000, idleMs = 3000 } = {}) {
  const seen = new Set();
  const look = async () => {
    const r = await rows(page);
    const screen = r.join('\n');
    if (!seen.has(screen)) { seen.add(screen); cam.keep(screen); }
    return r;
  };
  await clear(page, look);
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
      // the dialog's kind under `dialog`: the recorder writes a note's data over its name, so `kind` would replace it
      rec.note('permission', { answer: 'no', dialog: q.kind });
      await cam.lines(`ask${prompts.length + 1}`, q.top, q.end, { pad: 24, kmax: 1.5 }, `permission question ${prompts.length + 1}`);
      await cam.hold(4500);
      await page.keyboard.press('Escape');
      await page.waitForTimeout(1500);
      if (noRun) { await clear(page, look); await term.paste(page, noRun); await page.waitForTimeout(800); await send(page, look); }
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
