import fs from 'fs';
// The blessings engine's names for the food camera (data/store/food-vocab.json): node scripts/food_vocab.mjs <app dir> <out>
import zlib from 'zlib';
const app = process.argv[2];
const { openDataRecord } = await import(`${app}/src/services/blessingsEngine.mjs`);
const book = await import(`${app}/src/data/blessings/bookTable.mjs`);
const foods = JSON.parse(zlib.gunzipSync(fs.readFileSync(`${app}/public/blessings/foods.json.gz`))).records;
const records = [...book.BOOK_ROWS, ...foods.map(r => openDataRecord(r, book.BOOK_ROWS))];
// The names people say: no brand or packaging detail, no parenthesis, at most three words; one of each.
const clean = n => String(n || '').replace(/\[[^\]]*\]|\([^)]*\)/g, '').replace(/\s+/g, ' ').trim();
const seen = new Set(); const out = [];
for (const r of records) {
  const name = clean(r.name);
  if (!name || name.split(' ').length > 3 || /\d|®|™/.test(name)) continue;
  const key = name.replace(/[׳'"״]/g, '');
  if (seen.has(key)) continue;
  seen.add(key); out.push(name);
}
fs.writeFileSync(process.argv[3], JSON.stringify(out));
console.log(out.length, 'names,', JSON.stringify(out).length, 'chars');
