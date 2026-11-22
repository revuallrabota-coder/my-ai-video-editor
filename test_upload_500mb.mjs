// 500 MB multi-clip upload contract. Simulate metadata for 126 chunks
// rather than allocating the entire 500MB in CI.
import assert from "node:assert/strict";
import {createHmac,webcrypto} from "node:crypto";
import {readFile} from "node:fs/promises";
globalThis.crypto ??= webcrypto;
const source=await readFile(new URL("./cloudflare_launcher.js",import.meta.url),"utf8");
const {default:worker}=await import("data:text/javascript;base64,"+
  Buffer.from(source).toString("base64"));

const token="1234:TEST_500MB";
const owner="314159";
const params=new URLSearchParams({
  auth_date:String(Math.floor(Date.now()/1000)),
  user:JSON.stringify({id:Number(owner)})
});
const raw=[...params.entries()].sort(([a],[b])=>a.localeCompare(b))
  .map(([a,b])=>a+"="+b).join("\n");
const signingKey=createHmac("sha256","WebAppData").update(token).digest();
params.set("hash",createHmac("sha256",signingKey).update(raw).digest("hex"));
const base="https://test-500mb.workers.dev";
const origin="https://revuallrabota-coder.github.io";
const data=new Map();
let chunkReads=0;
const uploads={
  async put(key,value,options={}){data.set(key,{value,metadata:options.metadata??null,
    ttl:options.expirationTtl??null,expiration:options.expiration??null})},
  async get(key,type){
    if (/user-video:.*:(?:\d+)$/.test(key))chunkReads++;
    const row=data.get(key);
    if(!row)return null;
    return type==="json"?JSON.parse(row.value):row.value;
  },
  async list({prefix}){
    return {keys:[...data.entries()].filter(([name])=>name.startsWith(prefix))
      .map(([name,row])=>({name,metadata:row.metadata})),
      list_complete:true};
  },
  async delete(key){data.delete(key)}
};
const env={UPLOADS:uploads,TELEGRAM_BOT_TOKEN:token,
           OWNER_TELEGRAM_ID:owner,GITHUB_PAT:"fake-test-pat"};
let dispatched=0;
globalThis.fetch=async function(endpoint){
  assert.match(String(endpoint),/api.github.com\/repos\//);
  dispatched++;
  return new Response(null,{status:204});
};
async function request(path,method="GET",body,internal=false){
  const headers=internal?{Authorization:"Bearer "+token}:{
    Origin:origin,"X-Telegram-Init-Data":params.toString()
  };
  if(body && !(body instanceof ArrayBuffer))headers["Content-Type"]="application/json";
  const req=new Request(base+path,{method,headers,
    body:body instanceof ArrayBuffer?body:body?JSON.stringify(body):undefined});
  const response=await worker.fetch(req,env);
  let payload;
  try{payload=await response.json()}catch{payload=null}
  return {status:response.status,data:payload};
}
// Invalid upload *metadata* are rejected with 400. No binary 413 is
// involved because all request bodies here are tiny JSON manifests.
const health=(await request("/health")).data;
assert.equal(health.max_upload_mb,500);
assert.equal(health.max_files,12);
assert.equal(health.retention_days,3);
assert.equal(health.status_tracking,true);
assert.equal((await request("/upload/start","POST",{
  files:[{name:"a.mp4",size:250_000_000},{name:"b.mov",size:250_000_001}],
  size:500_000_001,settings:{}
})).status,400);
assert.equal((await request("/upload/start","POST",{
  files:Array.from({length:13},(_,i)=>({name:"clip"+i+".mp4",size:4096})),
  settings:{}
})).status,400);
assert.equal((await request("/upload/start","POST",{
  files:[{name:"x.mp4",size:5000},{name:"y.mov",size:5000}],
  size:5000,settings:{}
})).status,400);
const files=[
  {name:"first.mp4",size:200_000_000},
  {name:"second.mov",size:199_000_000},
  {name:"third.mp4",size:101_000_000}
];
const created=await request("/upload/start","POST",{
  files,size:500_000_000,settings:{
    mode:"my_style",subtitle_style:"reference_dynamic",
    caption_variant:"reference_soft",insert_style:"reference_soft",
    insert_density:"balanced",insert_sound:"off",
    top_title:"Разбор маникюра",top_title_mode:"always"
  }
});
assert.equal(created.status,201,JSON.stringify(created.data));
assert.equal(created.data.parts,126);
assert.equal(created.data.chunk_size,4_000_000);
assert.equal(data.get("user-video:"+created.data.upload_id+":meta").ttl,259200);
const id=created.data.upload_id;
const manifest=await uploads.get("user-video:"+id+":meta","json");
assert.equal(manifest.size,500_000_000);
assert.deepEqual(manifest.files.map(f=>[f.size,f.offset,f.parts]),[
  [200_000_000,0,50],[199_000_000,50,50],[101_000_000,100,26]
]);
assert.equal(manifest.settings.insert_style,"reference_soft");
assert.equal(manifest.settings.top_title,"Разбор маникюра");
assert.equal(manifest.settings.top_title_mode,"always");
assert.equal((await request("/upload/start","POST",{
  filename:"title.mp4",size:8000,
  settings:{top_title:"x".repeat(71),top_title_mode:"always"}
})).status,400);
assert.equal((await request("/upload/start","POST",{
  filename:"title.mp4",size:8000,
  settings:{top_title:"Test",top_title_mode:"invisible"}
})).status,400);
const prefix="user-video:"+id+":";
assert.equal((await request("/upload/"+id+"/0","PUT",new ArrayBuffer(4_000_000))).status,200);
assert.equal(data.get("user-video:"+id+":0").ttl,259200);
// First and last chunks of middle/end files test boundary arithmetic:
assert.equal((await request("/upload/"+id+"/99","PUT",new ArrayBuffer(1_000_000))).status,400);
assert.equal((await request("/upload/"+id+"/99","PUT",new ArrayBuffer(3_000_000))).status,200);
assert.equal((await request("/upload/"+id+"/125","PUT",new ArrayBuffer(1_000_000))).status,200);
assert.equal((await request("/upload/"+id+"/125","PUT",new ArrayBuffer(2_000_000))).status,400);
assert.deepEqual((await request("/upload/"+id+"/status")).data.uploaded_parts,[0,99,125]);
assert.equal((await request("/upload/"+id+"/finish","POST",{})).status,409);
assert.equal(dispatched,0);
for(let i=0;i<126;i++){
  if([0,99,125].includes(i))continue;
  const size=i>=100?(i===125?1_000_000:4_000_000):i>=50?
      (i===99?3_000_000:4_000_000):4_000_000;
  await uploads.put(prefix+i,new Uint8Array(0).buffer,{metadata:{bytes:size}});
}
assert.equal((await request("/upload/"+id+"/status")).data.uploaded_parts.length,126);
assert.equal(chunkReads,0,"Never fetch all 500 MB into a Worker at once");
assert.equal((await request("/upload/"+id+"/finish","POST",{})).status,202);
assert.equal(dispatched,1);
// Durable, owner-only progress persists independently of the iPad session.
assert.equal((await request("/internal/upload/"+id+"/progress","POST",{
  stage:"joining",message:"🎞️ Склеиваю 3 видео"
},true)).status,200);
let tracked=(await request("/upload/"+id+"/status")).data;
assert.equal(tracked.stage,"joining");
assert.equal(tracked.progress_percent,53);
assert.match(tracked.stage_label,/Склеиваю/);
assert.equal(tracked.retention_days,3);
assert.ok(tracked.expires_at>Date.now()+71*60*60*1000);
assert.equal(data.get("user-video:"+id+":progress:joining").ttl,259200);
assert.equal((await request("/internal/upload/"+id+"/progress","POST",{
  stage:"fake_stage"
},true)).status,400);
const privateDenied=await worker.fetch(new Request(base+"/upload/"+id+"/status"),env);
assert.equal(privateDenied.status,403);
// Simulate a large output. Every part expires at the SAME absolute time, so
// a slowly uploaded MP4 does not leave partially expired old chunks behind.
assert.equal((await request("/internal/upload/"+id+"/result/start","POST",{
  size:8_000_000
},true)).status,200);
for (let i=0;i<2;i++) {
  assert.equal((await request("/internal/upload/"+id+"/result/"+i,
    "PUT",new ArrayBuffer(4_000_000),true)).status,200);
}
const firstOutput=data.get("user-video:"+id+":output:0");
const secondOutput=data.get("user-video:"+id+":output:1");
assert.ok(firstOutput.expiration>Math.floor(Date.now()/1000)+71*3600);
assert.equal(firstOutput.expiration,secondOutput.expiration);
assert.equal((await request("/internal/upload/"+id+"/result/finish","POST",
  {},true)).status,200);
assert.equal(data.get("user-video:"+id+":meta").expiration,
             firstOutput.expiration,
             "Manifest and final MP4 chunks must expire at the same time");
assert.equal((await request("/internal/upload/"+id+"/progress","POST",{
  stage:"done",message:"✅ MP4 готов"
},true)).status,200);
tracked=(await request("/upload/"+id+"/status")).data;
assert.equal(tracked.state,"done");
assert.equal(tracked.stage,"done");
assert.equal(tracked.ready,true);
assert.equal(tracked.size,8_000_000);
assert.ok(Math.abs(tracked.expires_at-firstOutput.expiration*1000)<1000);
let cursor=0,cleanupCalls=0;
do {
  const reply=await request("/internal/upload/"+id+"/release?from="+cursor,
    "DELETE",null,true);
  assert.equal(reply.status,200);
  cursor=reply.data.next;
  cleanupCalls++;
  if(!reply.data.has_more)break;
} while(cleanupCalls<10);
assert.equal(cursor,126);
assert.ok(cleanupCalls>=5);
assert.ok(data.has("user-video:"+id+":meta"),
  "Keep small status metadata for 72h even after video source parts are freed");
assert.equal((await request("/upload/"+id+"/status")).data.stage,"done");
assert.equal(data.has("user-video:"+id+":0"),false);
assert.equal(data.has("user-video:"+id+":output:0"),true);
const protectedManifest=(await request("/internal/upload/"+id+"/manifest","GET",null,true)).data;
assert.equal(protectedManifest.files.length,3);
const denied=await worker.fetch(new Request(base+"/internal/upload/"+id+"/manifest"),env);
assert.equal(denied.status,401);
// Old single-file API remains usable after the multi-file upgrade.
const old=await request("/upload/start","POST",{
  filename:"single.mov",size:10_000_000,settings:{}
});
assert.equal(old.status,201);
assert.equal(old.data.parts,3);
// Private user-supplied ZIP packs travel after the video, without counting
// toward its 500MB source limit or getting published in a GitHub repository.
const privatePack=await request("/upload/start","POST",{
  files:[{name:"video.mp4",size:8_000_000}],size:8_000_000,
  assets:[
    {name:"Free-Animated-Icon-Sets(1).zip",size:20_000_000},
    {name:"PB_TrailerConstructionSFXLite.zip",size:10_000_000}
  ],settings:{}
});
assert.equal(privatePack.status,201,JSON.stringify(privatePack.data));
assert.equal(privatePack.data.parts,10);
const privateId=privatePack.data.upload_id;
const privateMeta=await uploads.get("user-video:"+privateId+":meta","json");
assert.deepEqual(privateMeta.assets.map(x=>[x.offset,x.parts,x.size]),[
  [2,5,20_000_000],[7,3,10_000_000]
]);
const resumePack=(await request("/upload/"+privateId+"/status")).data;
assert.equal(resumePack.input_size,8_000_000);
assert.equal(resumePack.input_parts,10);
assert.equal(resumePack.input_assets.length,2);
assert.equal((await request("/upload/"+privateId+"/9","PUT",
  new ArrayBuffer(2_000_000))).status,200);
assert.equal((await request("/upload/"+privateId+"/9","PUT",
  new ArrayBuffer(4_000_000))).status,400);
assert.equal((await request("/upload/start","POST",{
  files:[{name:"clip.mp4",size:8_000_000}],size:8_000_000,
  assets:[{name:"oversize.zip",size:100_000_001}],settings:{}
})).status,400);
// The iPad My Style wizard must never reference removed IDs at runtime.
// Static checks would not catch those since DOM calls only run after opening.
const html=await readFile(new URL("./index.html",import.meta.url),"utf8");
const knownIds=new Set([...html.matchAll(/\bid=["']([^"']+)["']/g)].map(m=>m[1]));
const referenced=[...html.matchAll(/byId\(['"]([^'"]+)['"]\)/g)].map(m=>m[1]);
const missingIds=[...new Set(referenced.filter(k=>!knownIds.has(k)))];
assert.deepEqual(missingIds,[],"All referenced UI controls must exist");
const radioModes=[...html.matchAll(/name="mode"\s+value="([^"]+)"/g)].map(m=>m[1]);
assert.deepEqual(radioModes,["Мой стиль"],"Only one real montage pipeline should be exposed");
for (const required of ["previewPhoto","previewPhotoImage","fontBig",
                        "fontSmall","replayPreview","previewKeyword",
                        "pauseRemoval","speed","launcherBase"]){
  assert.ok(knownIds.has(required),required+" missing from My Style");
}
const presets=html.match(/<select id="reelsPreset">([\s\S]*?)<\/select>/)?.[1];
assert.ok(presets,"Visual presets missing");
const styles=[...presets.matchAll(/value="([^"]+)"/g)].map(m=>m[1]);
assert.deepEqual(styles,["reference_soft","pink_tender","old_money","vintage_cinema","editorial","contour_talk","burgundy_brown_talk","custom"]);
console.log("✓ 500MB / 72h auto expiration / durable progress / secure private MP4 / paged source cleanup");
