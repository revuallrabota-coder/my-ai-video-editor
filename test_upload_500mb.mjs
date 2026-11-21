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
  async put(key,value,options={}){data.set(key,{value,metadata:options.metadata??null})},
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
const health=(await request("/health")).data;
assert.equal(health.max_upload_mb,500);
assert.equal(health.max_files,12);
assert.equal((await request("/upload/start","POST",{
  files:[{name:"a.mp4",size:250_000_000},{name:"b.mov",size:250_000_001}],
  size:500_000_001,settings:{}
})).status,413);
assert.equal((await request("/upload/start","POST",{
  files:Array.from({length:13},(_,i)=>({name:"clip"+i+".mp4",size:4096})),
  settings:{}
})).status,413);
assert.equal((await request("/upload/start","POST",{
  files:[{name:"x.mp4",size:5000},{name:"y.mov",size:5000}],
  size:5000,settings:{}
})).status,413);
const files=[
  {name:"first.mp4",size:200_000_000},
  {name:"second.mov",size:199_000_000},
  {name:"third.mp4",size:101_000_000}
];
const created=await request("/upload/start","POST",{
  files,size:500_000_000,settings:{
    mode:"my_style",subtitle_style:"reference_dynamic",
    caption_variant:"reference_soft",insert_style:"reference_soft",
    insert_density:"balanced",insert_sound:"off"
  }
});
assert.equal(created.status,201,JSON.stringify(created.data));
assert.equal(created.data.parts,126);
assert.equal(created.data.chunk_size,4_000_000);
const id=created.data.upload_id;
const manifest=(await request("/internal/upload/"+id+"/manifest","GET",null,true)).data;
assert.equal(manifest.size,500_000_000);
assert.deepEqual(manifest.files.map(f=>[f.size,f.offset,f.parts]),[
  [200_000_000,0,50],[199_000_000,50,50],[101_000_000,100,26]
]);
assert.equal(manifest.settings.insert_style,"reference_soft");
const prefix="user-video:"+id+":";
assert.equal((await request("/upload/"+id+"/0","PUT",new ArrayBuffer(4_000_000))).status,200);
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
const denied=await worker.fetch(new Request(base+"/internal/upload/"+id+"/manifest"),env);
assert.equal(denied.status,401);
// Old single-file API remains usable after the multi-file upgrade.
const old=await request("/upload/start","POST",{
  filename:"single.mov",size:10_000_000,settings:{}
});
assert.equal(old.status,201);
assert.equal(old.data.parts,3);
console.log("✓ 500MB / 3 ordered files / 126 chunks / resume / 4MB boundaries / auth / dispatch");
