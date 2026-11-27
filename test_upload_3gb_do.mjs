/* Storage contract and SQLite shard test for NO-CARD 3GB Worker v9.
   Never allocate a real 3GB binary blob in CI. Test actual SQL adapter with
   one 4MB chunk, fake the remaining chunk metadata to test routing/indexing. */
import assert from "node:assert/strict";
import {createHmac, webcrypto} from "node:crypto";
import {readFile} from "node:fs/promises";
globalThis.crypto??=webcrypto;
const src=await readFile(new URL("./cloudflare_launcher_do_v9.js",import.meta.url),"utf8");
const workerModule=await import("data:text/javascript;base64,"+
  Buffer.from(src).toString("base64"));
const worker=workerModule.default;
const Shard=workerModule.VideoChunkShard;
const token="12345:PRIVATE_TEST";
const owner=543210;
const qs=new URLSearchParams({
  auth_date:String(Math.floor(Date.now()/1000)),
  user:JSON.stringify({id:owner})
});
const raw=[...qs.entries()].sort(([a],[b])=>a.localeCompare(b))
  .map(([a,b])=>a+"="+b).join("\n");
const signKey=createHmac("sha256","WebAppData").update(token).digest();
qs.set("hash",createHmac("sha256",signKey).update(raw).digest("hex"));
const webOrigin="https://revuallrabota-coder.github.io";
const base="https://test-3gb.workers.dev";
let kvLists=0,kvWrites=0,githubDispatches=0;
const meta=new Map();
const kv={
  async put(name,value,opts={}){
    kvWrites++;meta.set(name,{value,metadata:opts.metadata||null});
  },
  async get(name,kind){const x=meta.get(name);if(!x)return null;
    return kind==="json"?JSON.parse(x.value):x.value;},
  async getWithMetadata(name,kind){const x=meta.get(name);return x?
    {value:x.value,metadata:x.metadata}:{value:null,metadata:null};},
  async delete(name){meta.delete(name)},
  async list(){kvLists++;throw Error("KV.list quota exhausted")}
};
class MockSqlite {
  constructor(){this.parts=new Map();}
  exec(query,...args){
    if(query.startsWith("CREATE TABLE"))return {toArray:()=>[]};
    if(query.startsWith("INSERT INTO pieces")){
      const [i,data,bytes]=args;
      this.parts.set(i,{data,bytes});
      return {toArray:()=>[]};
    }
    if(query.startsWith("SELECT data FROM pieces")){
      const row=this.parts.get(args[0]);
      return {toArray:()=>row?[{data:row.data}]:[]};
    }
    if(query.startsWith("SELECT i,bytes FROM pieces ORDER BY i")){
      const rows=[...this.parts.entries()].map(([i,row])=>({i,bytes:row.bytes}))
        .sort((a,b)=>a.i-b.i);
      return {toArray:()=>rows};
    }
    if(query.startsWith("DELETE FROM pieces WHERE i>=")){
      for(const i of this.parts.keys())if(i>=args[0]&&i<args[1])this.parts.delete(i);
      return {toArray:()=>[]};
    }
    if(query.startsWith("SELECT COUNT(*) AS n FROM pieces"))
      return {toArray:()=>[{n:this.parts.size}]};
    throw Error("Unexpected SQL: "+query);
  }
}
const shards=new Map();
const binding={
  idFromName(name){return name},
  get(name){
    if(!shards.has(name)){
      const sql=new MockSqlite();
      let alarmAt=null,deleteCount=0;
      const storage={
        sql,
        async getAlarm(){return alarmAt},
        async setAlarm(time){alarmAt=time},
        async deleteAll(){sql.parts.clear();alarmAt=null;deleteCount++}
      };
      const impl=new Shard({storage},{});
      shards.set(name,{sql,storage,impl,get deleteCount(){return deleteCount}});
    }
    return {fetch:request=>shards.get(name).impl.fetch(request)};
  }
};
const env={UPLOADS:kv,VIDEO_SHARDS:binding,
  TELEGRAM_BOT_TOKEN:token,OWNER_TELEGRAM_ID:String(owner),
  GITHUB_PAT:"FAKE_GITHUB_TEST"};
globalThis.fetch=async endpoint=>{
  assert.match(String(endpoint),/api.github.com\/repos\//);
  githubDispatches++;
  return new Response(null,{status:204});
};
async function send(path,method="GET",body,internal=false,environment=env){
  const headers=internal?{Authorization:"Bearer "+token}:
    {Origin:webOrigin,"X-Telegram-Init-Data":qs.toString()};
  if(body && !(body instanceof ArrayBuffer))headers["Content-Type"]="application/json";
  const req=new Request(base+path,{method,headers,
    body:body instanceof ArrayBuffer?body:body?JSON.stringify(body):undefined});
  const res=await worker.fetch(req,environment);
  let data;try{data=await res.json()}catch{data=null}
  return {status:res.status,data};
}
const health=(await send("/health")).data;
assert.equal(health.status,"online");
assert.equal(health.style_contract_version,9);
assert.equal(health.durable_storage_configured,true);
assert.equal(health.storage_mode,"do");
assert.equal(health.max_upload_mb,3000);
assert.equal(health.max_video_seconds,600);
const size=3_000_000_000;
const started=await send("/upload/start","POST",{
  files:[{name:"my-ten-minute-video.mp4",size}],
  size,settings:{mode:"my_style"}
});
assert.equal(started.status,201,JSON.stringify(started.data));
const id=started.data.upload_id;
assert.equal(started.data.parts,750);
assert.equal(started.data.storage,"do");
const m=JSON.parse(meta.get("user-video:"+id+":meta").value);
assert.equal(m.storage,"do");
assert.equal(m.size,size);
assert.equal(m.parts,750);
assert.equal(kvWrites,1,"binary files must never write to KV");
let response=await send("/upload/"+id+"/0","PUT",new ArrayBuffer(4_000_000));
assert.equal(response.status,200,JSON.stringify(response.data));
assert.equal(shards.get(id+":source:0").sql.parts.get(0).bytes,4_000_000);
assert.ok(shards.get(id+":source:0").storage.getAlarm());
assert.equal(kvWrites,1,"even the 4MB binary data stays outside KV");
// Mock upload completion by filling only metadata in each SQLite shard.
for(let i=1;i<750;i++){
  const name=id+":source:"+Math.floor(i/100);
  binding.get(name);
  shards.get(name).sql.parts.set(i,{data:new Uint8Array(0),bytes:4_000_000});
}
const progress=await send("/upload/"+id+"/status");
assert.equal(progress.status,200,JSON.stringify(progress.data));
assert.equal(progress.data.uploaded_parts.length,750);
assert.equal(progress.data.input_parts,750);
assert.equal(progress.data.storage,"do");
assert.equal(kvLists,0);
response=await send("/upload/"+id+"/finish","POST",{done:true});
assert.equal(response.status,202,JSON.stringify(response.data));
assert.equal(githubDispatches,1);
const manifest=await send("/internal/upload/"+id+"/manifest","GET",null,true);
assert.equal(manifest.status,200);
assert.equal(manifest.data.storage,"do");
const bodyResponse=await send("/internal/upload/"+id+"/chunk/0","GET",null,true);
assert.equal(bodyResponse.status,200);
// GitHub downloads the complete source before cleanup. 30-piece cleanups
// must not remove the output shards or unrelated project data.
for(let offset=0;offset<750;offset+=30){
  const resp=await send("/internal/upload/"+id+"/release?from="+offset,
                        "DELETE",undefined,true);
  assert.equal(resp.status,200,JSON.stringify(resp.data));
}
assert.equal(shards.get(id+":source:0").sql.parts.size,0);
assert.ok(shards.get(id+":source:0").deleteCount>=1);
const outputSize=512_000_000;
response=await send("/internal/upload/"+id+"/result/start",
                   "POST",{size:outputSize},true);
assert.equal(response.status,200,JSON.stringify(response.data));
const uploadResult=await send("/internal/upload/"+id+"/result/0","PUT",
                               new ArrayBuffer(4_000_000),true);
assert.equal(uploadResult.status,200);
assert.equal(shards.get(id+":output:0").sql.parts.get(0).bytes,4_000_000);
for(let i=1;i<128;i++){
  const name=id+":output:"+Math.floor(i/100);
  binding.get(name);
  shards.get(name).sql.parts.set(i,{data:new Uint8Array(0),bytes:4_000_000});
}
response=await send("/internal/upload/"+id+"/result/finish","POST",{},true);
assert.equal(response.status,200,JSON.stringify(response.data));
const resultStatus=await send("/upload/"+id+"/status");
assert.equal(resultStatus.data.ready,true);
assert.equal(resultStatus.data.storage,"do");
assert.equal((await send("/upload/"+id+"/result/0")).status,200);
// Signed Safari download streams a precise HTTP byte range; never holds 3GB.
const masterLink=await send("/upload/"+id+"/master-link","GET");
assert.equal(masterLink.status,200,JSON.stringify(masterLink.data));
assert.ok(masterLink.data.url.includes("/master/"+id+"?expires="));
const download=await worker.fetch(new Request(masterLink.data.url,{
  headers:{"Range":"bytes=0-19"}
}),env);
assert.equal(download.status,206);
assert.equal(download.headers.get("content-length"),"20");
assert.equal(download.headers.get("content-range"),"bytes 0-19/512000000");
assert.equal((await download.arrayBuffer()).byteLength,20);
const broken=new URL(masterLink.data.url);
broken.searchParams.set("signature","0".repeat(64));
assert.equal((await worker.fetch(new Request(broken),env)).status,403);
const invalidRange=await worker.fetch(new Request(masterLink.data.url,{
  headers:{"Range":"bytes=512000000-512000005"}
}),env);
assert.equal(invalidRange.status,416);
assert.equal(kvLists,0);
// Legacy small-file projects continue via KV if user hasn't deployed DO yet.
const fallbackEnv={...env,VIDEO_SHARDS:undefined};
const kvHealth=(await send("/health","GET",undefined,false,fallbackEnv)).data;
assert.equal(kvHealth.max_upload_mb,500);
assert.equal(kvHealth.durable_storage_configured,false);
const refusal=await send("/upload/start","POST",{
  files:[{name:"too-large.mp4",size:700_000_000}],
  size:700_000_000
},false,fallbackEnv);
assert.equal(refusal.status,400);
console.log("✓ free DO v9: 3GB/750 chunks/8 SQLite shards; alarms, source cleanup, signed range downloads, 512MB master, no KV binary/list, KV fallback");
