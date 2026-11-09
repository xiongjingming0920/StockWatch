import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {runInThisContext} from 'node:vm';
import {deflateRawSync} from 'node:zlib';
globalThis.window={};runInThisContext(await readFile(new URL('../frontend/vendor/zip.js',import.meta.url),'utf8'));
function crc32(b){let c=0xffffffff;for(const x of b){c^=x;for(let j=0;j<8;j++)c=(c>>>1)^((c&1)?0xedb88320:0)}return(c^0xffffffff)>>>0}
function zip(items){let local=[],central=[],offset=0;for(const item of items){const name=Buffer.from(item.name),data=Buffer.from(item.data),packed=deflateRawSync(data),crc=crc32(data),size=item.declared??data.length;const l=Buffer.alloc(30);l.writeUInt32LE(0x04034b50);l.writeUInt16LE(item.flags||0,6);l.writeUInt16LE(8,8);l.writeUInt32LE(crc,14);l.writeUInt32LE(packed.length,18);l.writeUInt32LE(size,22);l.writeUInt16LE(name.length,26);local.push(l,name,packed);const c=Buffer.alloc(46);c.writeUInt32LE(0x02014b50);c.writeUInt16LE(item.flags||0,8);c.writeUInt16LE(8,10);c.writeUInt32LE(crc,16);c.writeUInt32LE(packed.length,20);c.writeUInt32LE(size,24);c.writeUInt16LE(name.length,28);c.writeUInt32LE(offset,42);central.push(c,name);offset+=l.length+name.length+packed.length}const cd=Buffer.concat(central),e=Buffer.alloc(22);e.writeUInt32LE(0x06054b50);e.writeUInt16LE(items.length,8);e.writeUInt16LE(items.length,10);e.writeUInt32LE(cd.length,12);e.writeUInt32LE(offset,16);return new Uint8Array(Buffer.concat([...local,cd,e]))}
const api=window.StockWatchZip,b=zip([{name:'data.csv',data:'a,b\n1,2'},{name:'报告.txt',data:'你好'}]),entries=api.list(b);
assert.equal(entries.length,2);assert.equal(new TextDecoder().decode(await api.extract(b,entries[1])),'你好');
assert.throws(()=>api.list(zip([{name:'../x.txt',data:'x'}])));
assert.throws(()=>api.list(zip([{name:'a.txt',data:'x'},{name:'a.txt',data:'y'}])));
assert.throws(()=>api.list(zip([{name:'x.txt',data:'x',flags:1}])));
assert.throws(()=>api.list(zip([{name:'x.zip',data:'x'}])));
const bomb=zip([{name:'x.txt',data:'X'.repeat(300000),declared:100}]);await assert.rejects(()=>api.extract(bomb,api.list(bomb)[0]));
console.log('ZIP bounds, selection and streaming checks passed');
