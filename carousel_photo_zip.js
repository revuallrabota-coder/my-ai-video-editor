/* Minimal store-only ZIP for user-selected photos on iPad.
 * Only user-approved local images are packed; nothing is uploaded before
 * they press "Смонтировать Reels". No third-party ZIP CDN or API keys.
 */
(function(root){
  "use strict";
  function crc32(bytes){
    var n=0xFFFFFFFF;
    for(var i=0;i<bytes.length;i++){
      n^=bytes[i];
      for(var j=0;j<8;j++)n=(n>>>1)^(0xEDB88320&-(n&1));
    }
    return (n^0xFFFFFFFF)>>>0;
  }
  function header(size){return new Uint8Array(size);}
  function makeView(a){return new DataView(a.buffer,a.byteOffset,a.byteLength);}
  async function makeCarouselPhotoZip(files){
    files=Array.from(files||[]);
    if(!files.length)return null;
    if(files.length<3 || files.length>12)
      throw new Error("Для настоящей карусели выбери 3–12 разных фотографий.");
    var total=files.reduce(function(n,f){return n+f.size},0);
    if(total>80000000)
      throw new Error("Фотографии для карусели должны занимать до 80 МБ суммарно.");
    if(files.some(function(f){
      return !(/\.(png|jpg|jpeg|webp)$/i.test(f.name))||
             f.size<128||f.size>18000000;
    }))throw new Error("Для карусели подходят JPG, PNG или WebP до 18 МБ за фото.");
    var encoder=new TextEncoder();
    var pieces=[],centers=[],offset=0,centralBytes=0;
    for(var i=0;i<files.length;i++){
      var file=files[i];
      var extension=file.name.split(".").pop().toLowerCase();
      var name=encoder.encode("carousel_"+String(i+1).padStart(2,"0")+"."+extension);
      var bytes=new Uint8Array(await file.arrayBuffer());
      var checksum=crc32(bytes);
      var local=header(30+name.length);
      var l=makeView(local);
      l.setUint32(0,0x04034b50,true);
      l.setUint16(4,20,true);
      l.setUint16(6,0x800,true); // UTF-8 file names
      l.setUint16(8,0,true);     // Stored, no extra CPU for compression
      l.setUint32(14,checksum,true);
      l.setUint32(18,bytes.length,true);
      l.setUint32(22,bytes.length,true);
      l.setUint16(26,name.length,true);
      local.set(name,30);
      var central=header(46+name.length);
      var c=makeView(central);
      c.setUint32(0,0x02014b50,true);
      c.setUint16(4,20,true);
      c.setUint16(6,20,true);
      c.setUint16(8,0x800,true);
      c.setUint32(16,checksum,true);
      c.setUint32(20,bytes.length,true);
      c.setUint32(24,bytes.length,true);
      c.setUint16(28,name.length,true);
      c.setUint32(42,offset,true);
      central.set(name,46);
      pieces.push(local,bytes);
      centers.push(central);
      offset+=local.length+bytes.length;
      centralBytes+=central.length;
    }
    var eocd=header(22),end=makeView(eocd);
    end.setUint32(0,0x06054b50,true);
    end.setUint16(8,files.length,true);
    end.setUint16(10,files.length,true);
    end.setUint32(12,centralBytes,true);
    end.setUint32(16,offset,true);
    var modified=Math.max.apply(null,files.map(function(f){return f.lastModified||0;}));
    return new File([...pieces,...centers,eocd],"user_carousel_photos.zip",{
      type:"application/zip",lastModified:modified||0
    });
  }
  root.makeCarouselPhotoZip=makeCarouselPhotoZip;
  if(typeof module!=="undefined" && module.exports){
    module.exports={makeCarouselPhotoZip:makeCarouselPhotoZip};
  }
})(typeof window!=="undefined"?window:globalThis);
