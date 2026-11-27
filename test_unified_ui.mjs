// Regression: iPad Mini App must offer one My Style workflow with a
// photo-backed, font-sensitive preview and no dead controls or old modes.
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
const html=readFileSync("index.html","utf8");
const ids=[...html.matchAll(/\bid="([^"]+)"/g)].map(m=>m[1]);
const defined=new Set(ids);
assert.equal(ids.length,defined.size,"Duplicate DOM IDs make iPad previews unreliable");
const requested=[...html.matchAll(/byId\('([^']+)'\)/g)].map(m=>m[1]);
assert.deepEqual([...new Set(requested.filter(id=>!defined.has(id)))],[],
  "All JS controls must exist after removing legacy editor pages");
const pages=[...html.matchAll(/<section class="card page(?: active)?" data-page="(\d+)"/g)]
  .map(m=>Number(m[1]));
assert.deepEqual(pages,[0,1,2,3],"No redundant mode-selection page");
assert.match(html,/var names=\['Видео','Шрифты','Эффекты','Итог'\]/);
const radio=[...html.matchAll(/<input[^>]+name="mode"[^>]*>/g)];
assert.equal(radio.length,1,"Only one supported end-to-end video workflow");
assert.match(radio[0][0],/value="Мой стиль"/);
assert.match(radio[0][0],/checked/);
assert.doesNotMatch(html,/<option[^>]*>[^<]*(?:Старый плавный Zoom|Усиленный \(старый\)|старый вариант фразами)/i);
const photo=html.match(/<input[^>]*id="previewPhoto"[^>]*>/)?.[0];
assert.ok(photo);
assert.match(photo,/type="file"/);
assert.match(photo,/accept="image\/\*"/);
assert.match(html,/<img[^>]+id="previewPhotoImage"/);
assert.match(html,/byId\('previewPhoto'\)\.addEventListener\('change'/);
assert.match(html,/URL\.createObjectURL\(file\)/);
assert.match(html,/function applySampleFont\(node,preset\)/);
assert.match(html,/byId\('fontBig'\)\.value/);
assert.match(html,/byId\('fontSmall'\)\.value/);
assert.match(html,/style\.fontFamily=item\.family/);
assert.match(html,/style\.fontStyle=item\.italic/);
assert.match(html,/style\.fontWeight=item\.weight/);
assert.match(html,/byId\('replayPreview'\)\.addEventListener\('click',replaySample\)/);
assert.match(html,/byId\('reelsPreset'\)\.addEventListener\('change'/);
assert.match(html,/id="checkWorkerConnection"/,"Must expose actual Worker diagnostics on iPad");
assert.match(html,/id="workerConnectionResult"/);
assert.match(html,/id="workerHealthLink"/);
assert.match(html,/function connectedWorkerURL\(\)/);
assert.match(html,/async function checkWorkerConnection\(\)/);
assert.match(html,/!\[7,8,9\]\.includes\(workerHealth\.style_contract_version\)/);
assert.match(html,/id="guideEffect"/);
assert.match(html,/guideEffect:configuredGuideEffect\(\)/);
assert.match(html,/guide_effect:\(s.motionInserts\|\|manualFx\)\?s.guideEffect:'off'/);
assert.match(html,/start.accepted_guide_effect!==settings.guide_effect/);
assert.match(html,/Приложение проверяет адрес/);
const presets=html.slice(html.indexOf("var reelPresets={"),
                          html.indexOf("byId('reelsPreset').addEventListener"));
assert.ok(presets.length>30 && presets.length<1400);
for(const setting of ["speed","pauseRemoval","camera","audio","insert","motion","sound"]){
  assert.doesNotMatch(presets,new RegExp(setting,"i"),
    "Changing a visual preset must not override "+setting);
}
const settings=html.slice(html.indexOf("function buildRenderSettings()"),
                          html.indexOf("function telegramProof()"));
for(const setting of ["mode:modeForServer(s.mode)",
                      "speed:s.speed","pause_removal:s.pauseRemoval",
                      "font_profile:s.largeFont",
                      "small_font_profile:s.smallFont",
                      "animation_style:s.captionAnimation",
                      "insert_style:s.motionInserts"]){
  assert.ok(settings.includes(setting),"Unified pipeline missing "+setting);
}
assert.match(html,/<option value="1\.2" selected>/);
assert.match(html,/<option value="tight" selected>/);
const open=html.indexOf("<script>",html.indexOf("</style>"));
const close=html.indexOf("</script>",open);
assert.ok(open>=0 && close>open);
new Function(html.slice(open+"<script>".length,close));
console.log("✓ Single My Style flow, 4 steps, no missing DOM IDs, font+photo preview, independent controls");
