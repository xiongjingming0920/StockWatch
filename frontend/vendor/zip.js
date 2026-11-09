// ZIP files are examined locally. Bounds apply to compressed bytes, entries and streamed output.
(function(){
const MAX_ARCHIVE=2*1024*1024,MAX_FILE=200*1024,MAX_TOTAL=4*1024*1024,MAX_ENTRIES=100;
function fail(){throw Error('ZIP 格式无效、不受支持或超出安全限制。')}
function list(bytes){
 if(bytes.length>MAX_ARCHIVE)throw Error('ZIP 压缩包不能超过 2 MB。');
 const d=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength),len=bytes.length;let end=-1;
 for(let p=len-22;p>=Math.max(0,len-65557);p--){if(d.getUint32(p,true)===0x06054b50 && p+22+d.getUint16(p+20,true)===len){end=p;break}}
 if(end<0)fail();const disk=d.getUint16(end+4,true),cdDisk=d.getUint16(end+6,true),n=d.getUint16(end+10,true),size=d.getUint32(end+12,true),offset=d.getUint32(end+16,true);
 if(disk||cdDisk||n!==d.getUint16(end+8,true)||n>MAX_ENTRIES||offset+size!==end||n===65535)fail();
 let pos=offset,total=0,results=[];const seen=new Set();const decoder=new TextDecoder('utf-8',{fatal:true});
 for(let i=0;i<n;i++){
  if(pos+46>end||d.getUint32(pos,true)!==0x02014b50)fail();
  const flags=d.getUint16(pos+8,true),method=d.getUint16(pos+10,true),crc=d.getUint32(pos+16,true),packed=d.getUint32(pos+20,true),unpacked=d.getUint32(pos+24,true),namesz=d.getUint16(pos+28,true),extra=d.getUint16(pos+30,true),comment=d.getUint16(pos+32,true),diskNo=d.getUint16(pos+34,true),local=d.getUint32(pos+42,true),next=pos+46+namesz+extra+comment;
  if(next>end||flags&1||diskNo||packed===0xffffffff||unpacked===0xffffffff||local>=offset)fail();
  let name;try{name=decoder.decode(bytes.subarray(pos+46,pos+46+namesz))}catch{throw Error('ZIP 内文件名需为 UTF-8 编码。')}
  if(!name||name.length>300||name.includes('\\')||name.startsWith('/')||/^[a-z]:/i.test(name)||name.split('/').some(x=>x==='..'||x==='.')||/[\x00-\x1f]/.test(name))fail();
  if(seen.has(name))throw Error('ZIP 中存在重复文件名。');seen.add(name);
  if(/\.zip$/i.test(name))throw Error('暂不支持包含嵌套 ZIP 的压缩包。');
  total+=unpacked;if(total>MAX_TOTAL)throw Error('ZIP 解压总大小超出 4 MB。');
  if(!name.endsWith('/')&&/\.(csv|txt)$/i.test(name)){
   if(unpacked>MAX_FILE)throw Error('ZIP 内每个 CSV 或 TXT 文件不能超过 200 KB。');
   if(![0,8].includes(method))throw Error('ZIP 使用了不支持的压缩方式。');
   results.push({name,flags,method,crc,packed,unpacked,local,archiveDataEnd:offset});
  }
  pos=next;
 }
 if(pos!==end)fail();if(!results.length)throw Error('压缩包中没有 CSV 或 TXT 文件。');return results;
}
function crc32(a){let c=0xffffffff;for(const x of a){c^=x;for(let j=0;j<8;j++)c=(c>>>1)^((c&1)?0xedb88320:0)}return (c^0xffffffff)>>>0}
async function extract(bytes,e){
 const d=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength),p=e.local;if(p+30>bytes.length||d.getUint32(p,true)!==0x04034b50||d.getUint16(p+6,true)!==e.flags||d.getUint16(p+8,true)!==e.method)fail();
 const nameLength=d.getUint16(p+26,true),start=p+30+nameLength+d.getUint16(p+28,true),end=start+e.packed;if(start>e.archiveDataEnd||end>e.archiveDataEnd||end<start)fail();let localName;try{localName=new TextDecoder('utf-8',{fatal:true}).decode(bytes.subarray(p+30,p+30+nameLength))}catch{fail()}if(localName!==e.name)fail();const compressed=bytes.subarray(start,end);let parts=[],count=0;
 if(e.method===0){if(compressed.length>MAX_FILE)fail();parts=[compressed];count=compressed.length}
 else{
  let stream;try{let off=0;const input=new ReadableStream({pull(controller){if(off>=compressed.length){controller.close();return}const chunk=compressed.subarray(off,Math.min(off+256,compressed.length));off+=chunk.length;controller.enqueue(chunk)}});stream=input.pipeThrough(new DecompressionStream('deflate-raw')).getReader()}catch{throw Error('当前浏览器不支持 ZIP 解压，请升级浏览器或单独上传文件。')}
  try{while(true){const {done,value}=await stream.read();if(done)break;count+=value.byteLength;if(count>MAX_FILE){await stream.cancel();throw Error('ZIP 中文件解压后超过 200 KB。')}parts.push(value)}}catch(error){try{await stream.cancel()}catch{}throw error}
 }
 if(count!==e.unpacked)fail();const out=new Uint8Array(count);let at=0;for(const part of parts){out.set(part,at);at+=part.length}if(crc32(out)!==e.crc)throw Error('ZIP 文件校验失败，请重新压缩。');return out;
}
window.StockWatchZip={list,extract};
})();
