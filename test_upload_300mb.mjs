// Fast protocol regression without allocating a 300 MB video in CI.
import assert from "node:assert/strict";
import {createHmac,webcrypto} from "node:crypto";
import {readFile} from "node:fs/promises";
globalThis.crypto ??= webcrypto;
const source=await readFile(new URL("./cloudflare_launcher.js",import.meta.url),"utf8");
const {default:worker}=await import("data:text/javascript;base64,"+
  Buffer.from(source).toString("base64"));

const token="1234:TEST_300MB";
const owner="314159";
const payload=new URLSearchParams({
  auth_date:String(Math.floor(Date.now()/1000)),
  user:JSON.stringify({id:Number(owner)})
});
const raw=[...payload.entries()].sort(([a],[b])=>a.localeCompare(b))
  .map(([a,b])=>a+"="+b).join("\n");
const signingKey=createHmac("sha256","WebAppData").update(token).digest();
payload.set("hash",createHmac("sha256",signingKey).update(raw).digest("hex"));
const initData=payload.toString();
const base="https://test-300mb.workers.dev";
const origin="https://revuallrabota-coder.github.io";
const data=new Map();
const uploads={
  async put(key,value,options={}){
    data.set(key,{value,metadata:options.metadata??null});
  },
  async get(key,type){
    const row=data.get(key);
    if(!row)return null;
    if(type==="json")return JSON.parse(row.value);
    return row.value;
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
    Origin:origin,"X-Telegram-Init-Data":initData
  };
  if(body && !(body instanceof ArrayBuffer))headers["Content-Type"]="application/json";
  const req=new Request(base+path,{method,headers,
    body:body instanceof ArrayBuffer?body:body?JSON.stringify(body):undefined});
  const response=await worker.fetch(req,env);
  return {status:response.status,data:await response.json()};
}
assert.equal((await request("/health")).data.max_upload_mb,300);
assert.equal((await request("/upload/start","POST",{
  filename:"recording.mov",size:300_000_001,settings:{}
})).status,413);
const created=await request("/upload/start","POST",{
  filename:"recording.mov",size:300_000_000,settings:{
    mode:"my_style",subtitle_style:"reference_dynamic",
    caption_variant:"reference_soft",insert_style:"reference_soft",
    insert_density:"balanced",insert_sound:"off"
  }
});
assert.equal(created.status,201,JSON.stringify(created.data));
assert.equal(created.data.parts,75);
assert.equal(created.data.chunk_size,4_000_000);
const id=created.data.upload_id;
const meta=await uploads.get("user-video:"+id+":meta","json");
assert.equal(meta.size,300_000_000);
assert.equal(meta.parts,75);
assert.equal(meta.settings.insert_style,"reference_soft");
const prefix="user-video:"+id+":";
const first=await uploads.put(prefix+"0",new Uint8Array(4_000_000).buffer,
                              {metadata:{bytes:4_000_000}});
assert.equal((await request("/upload/"+id+"/status")).data.uploaded_parts.length,1);
assert.equal((await request("/upload/"+id+"/finish","POST",{})).status,409);
assert.equal(dispatched,0);
for(let i=1;i<75;i++){
  await uploads.put(prefix+i,new Uint8Array(0).buffer,
                   {metadata:{bytes:4_000_000}});
}
const resumed=await request("/upload/"+id+"/status");
assert.equal(resumed.data.uploaded_parts.length,75);
assert.equal(resumed.data.input_size,300_000_000);
const done=await request("/upload/"+id+"/finish","POST",{});
assert.equal(done.status,202,JSON.stringify(done.data));
assert.equal(dispatched,1);
const privateDenied=await worker.fetch(
  new Request(base+"/internal/upload/"+id+"/manifest"),env);
assert.equal(privateDenied.status,401);
console.log("✓ 300MB max / 75 chunks / no bulk read / resume / auth / dispatch");
