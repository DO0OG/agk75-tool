// 웹 사전 검사: node tests/i18n_check.js '["Off","Wave",...]' (인자 = 효과 이름 목록)
// 세 언어의 키 집합·자리표시자가 같은지, 화면 코드가 쓰는 키가 모두 있는지, t() 치환을 확인한다.
const fs = require("fs");
const path = require("path");
const { I18N_DICT, I18N, t } = require("../agk75/web/i18n.js");

const errors = [];
const fail = (m) => errors.push(m);
const langs = Object.keys(I18N_DICT);
if (langs.join() !== "ko,en,zh") fail("languages: " + langs);

const ko = Object.keys(I18N_DICT.ko);
const holes = (s) => (s.match(/\{\w+\}/g) || []).sort().join();
for (const l of langs) {
  const keys = Object.keys(I18N_DICT[l]);
  for (const k of ko) if (!(k in I18N_DICT[l])) fail(`${l} is missing ${k}`);
  for (const k of keys) if (!(k in I18N_DICT.ko)) fail(`${l} has extra ${k}`);
  for (const k of keys) {
    if (!I18N_DICT[l][k]) fail(`${l} empty ${k}`);
    else if (k in I18N_DICT.ko && holes(I18N_DICT[l][k]) !== holes(I18N_DICT.ko[k])) fail(`${l} placeholders differ ${k}`);
  }
}

const dir = path.join(__dirname, "..", "agk75", "web");
const used = new Set();
for (const f of fs.readdirSync(dir).filter((n) => n.endsWith(".js") && n !== "i18n.js")) {
  const src = fs.readFileSync(path.join(dir, f), "utf8");
  for (const m of src.matchAll(/\bt\(\s*"([\w.]+)"\s*[,)]/g)) used.add(m[1]);
  for (const m of src.matchAll(/\b(?:label|legend):\s*"([\w.]+)"/g)) used.add(m[1]);
  for (const m of src.matchAll(/\bt\(\s*(?:st\.\w+|j\.\w+|s\.package|on)\s*\?\s*"([\w.]+)"\s*:\s*"([\w.]+)"/g)) { used.add(m[1]); used.add(m[2]); }
}
for (const k of used) if (!(k in I18N_DICT.ko)) fail(`code uses unknown key ${k}`);

// 동적 키: 효과 이름, 자기 축 항목, 장치 옵션
for (const n of JSON.parse(process.argv[2] || "[]")) if (!("fx." + n in I18N_DICT.ko)) fail("no gloss for effect " + n);
for (const k of ["travel", "lift", "dead", "rt_press", "rt_lift"]) if (!("mag." + k in I18N_DICT.ko)) fail("mag." + k);
for (const k of ["win_lock", "mac", "wasd_arrow", "led_off", "side_led_off", "keyboard_lock", "fn_matrix", "power_save"]) {
  if (!("opt." + k in I18N_DICT.ko)) fail("opt." + k);
}

// t() 동작
I18N.lang = "en";
if (t("toast.profile", { n: 3 }) !== "Profile 3 applied") fail("en substitution");
I18N.lang = "zh";
if (!t("mag.progress", { n: 1, total: 2, idx: 7 }).includes("1/2") || !t("mag.progress", { n: 1, total: 2, idx: 7 }).includes("7")) fail("zh substitution");
if (t("rate.title") !== "回报率" || t("mag.travel") !== "触发行程") fail("zh terms");
I18N.lang = "ko";
if (t("no.such.key") !== "no.such.key") fail("missing key fallback");
if (t("toast.profile") !== "프로필 {n} 적용됨") fail("missing params keep placeholders");
I18N.lang = "xx";
if (t("nav.keys") !== I18N_DICT.ko["nav.keys"]) fail("unknown language falls back to ko");

if (errors.length) { console.error(errors.join("\n")); process.exit(1); }
console.log(JSON.stringify({ keys: ko.length, used: used.size }));
