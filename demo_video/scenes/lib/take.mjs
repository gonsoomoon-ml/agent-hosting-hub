// The camera of a take, with the text of the screen kept at every shot (<out>/<take>.texts.txt, next to the camlog),
// so that a take can be checked for an account ID or an e-mail address without reading every frame.
//   const cam = kit({ page, rec, option });
//   await cam.focus('steps', '#panel-steps', { pad: 16, kmax: 1.6 }, 'the seven steps');
import fs from 'node:fs';
import path from 'node:path';
import { term } from './plugin.mjs';

export function kit({ page, rec, option }) {
  const name = option('--name', 'take');
  const out = option('--out', 'raw');
  const file = path.join(out, `${name}.texts.txt`);
  fs.mkdirSync(out, { recursive: true });
  fs.writeFileSync(file, '');
  async function dump(key) {
    let text;
    try {
      text = await page.evaluate(() => {
        const rows = document.querySelectorAll('.xterm-rows > div');
        if (rows.length) return [...rows].map(d => d.textContent.replace(/\s+$/, '')).join('\n');
        return document.body.innerText;
      });
    } catch (error) {
      text = `(no text: ${error.message.split('\n')[0]})`;
    }
    fs.appendFileSync(file, `== ${rec.now().toFixed(2)} ${key}\n${text}\n`);
  }
  return {
    name,
    dump,
    async focus(key, selector, opts = {}, label) { const r = await rec.focus(key, selector, opts, label); await dump(key); return r; },
    async region(key, x, y, w, h, opts = {}, label) { const r = await rec.region(key, x, y, w, h, opts, label); await dump(key); return r; },
    async reset(key = 'wide', label) { const r = await rec.reset(key, label); await dump(key); return r; },
    /** Terminal rows from the row holding `first` to the last row holding `last`; text not on screen is a missing shot. */
    async rows(key, first, last, opts = {}, label) {
      const r = await term.rowsRect(page, first, last);
      if (!r) { console.warn(`rows ${key}: '${first}' is not on the screen`); const m = await rec.shot(key, 'null', label); await dump(key); return m; }
      const w = Math.min(r.w, opts.maxW ?? 1900);
      const shot = await rec.region(key, r.x, r.y, w, r.h, { pad: opts.pad ?? 28, kmax: opts.kmax ?? 1.6, anchorTop: opts.anchorTop ?? true }, label);
      await dump(key);
      return shot;
    },
    /** Terminal rows i..j (0-based indexes of the visible rows), framed from the top. */
    async lines(key, i, j, opts = {}, label) {
      const r = await page.evaluate(([a, b]) => {
        const top = window.__cam.rect(`.xterm-rows > div:nth-child(${a + 1})`);
        const bottom = window.__cam.rect(`.xterm-rows > div:nth-child(${b + 1})`);
        return top && bottom ? { x: top.x, y: top.y, w: Math.max(top.w, bottom.w), h: bottom.y + bottom.h - top.y } : null;
      }, [i, j]);
      if (!r) { const m = await rec.shot(key, 'null', label); await dump(key); return m; }
      const shot = await rec.region(key, r.x, r.y, Math.min(r.w, 1900), r.h, { pad: opts.pad ?? 28, kmax: opts.kmax ?? 1.6, anchorTop: opts.anchorTop ?? true }, label);
      await dump(key);
      return shot;
    },
    hold: ms => rec.sleep(ms),
    note: (kind, data) => rec.note(kind, data),
  };
}
