// The blessings engine's table for הרב בארי יעקב (data/store/food-blessings.json): each food's names, its blessing before
// and after and its source, so "מה מברכים על…" is answered from the verified table before any model memory.
// Usage: node scripts/food_blessings.mjs <app dir> <out>
import fs from 'fs';
import zlib from 'zlib';
const app = process.argv[2];
const { openDataRecord, presentRecord } = await import(`${app}/src/services/blessingsEngine.mjs`);
const book = await import(`${app}/src/data/blessings/bookTable.mjs`);
const { VERIFIED_RECORDS } = await import(`${app}/src/data/blessings/verifiedCorrections.mjs`);
const foods = JSON.parse(zlib.gunzipSync(fs.readFileSync(`${app}/public/blessings/foods.json.gz`))).records;
const records = [...book.BOOK_ROWS, ...book.BOOK_HALACHA_RECORDS, ...VERIFIED_RECORDS, ...foods.map(r => openDataRecord(r, book.BOOK_ROWS))];
const out = [];
for (const r of records) {
  const v = presentRecord(r, { nusach: 'edot' });
  if (!v.before?.label || !v.after?.label || r.kind === 'pending' || r.kind === 'conditional') continue; // verified only
  out.push({ names: [r.name, ...(r.aliases || [])].filter(Boolean), brand: r.brand || '', before: v.before.label, after: v.after.label, cite: r.kind === 'book' ? (v.sources?.[0] || '') : [v.ruleTitle, v.ruleSources?.[0]?.citation || v.ruleSources?.[0]?.title || ''].filter(Boolean).join(' — ') });
}
fs.writeFileSync(process.argv[3], JSON.stringify(out));
console.log(out.length, 'foods with a verified blessing');
