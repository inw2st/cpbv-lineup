import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {applyTheme,readTheme,THEME_KEY} from '../src/theme.ts';

const values=new Map();
globalThis.localStorage={getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)};
globalThis.document={documentElement:{dataset:{},style:{}}};
test('theme follows system unless an explicit mode is chosen',()=>{
  applyTheme('system',true);assert.equal(document.documentElement.dataset.theme,'dark');
  applyTheme('system',false);assert.equal(document.documentElement.dataset.theme,'light');
  applyTheme('light',true);assert.equal(document.documentElement.dataset.theme,'light');
  applyTheme('dark',false);assert.equal(document.documentElement.dataset.theme,'dark');
  assert.equal(document.documentElement.style.colorScheme,'dark');
});
test('the selection is retained for the next UI bootstrap',()=>{
  applyTheme('dark',false);assert.equal(readTheme(),'dark');
  values.set(THEME_KEY,'unexpected');assert.equal(readTheme(),'system');
});
test('disabled browser storage does not prevent applying a theme',()=>{
  const previous=globalThis.localStorage;
  globalThis.localStorage={getItem(){throw Error('off')},setItem(){throw Error('off')}};
  assert.equal(readTheme(),'system');applyTheme('dark',false);
  assert.equal(document.documentElement.dataset.theme,'dark');globalThis.localStorage=previous;
});
function luminance(hex){
  const rgb=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);
  return rgb.reduce((sum,v,i)=>sum+v*[.2126,.7152,.0722][i],0);
}
test('core light and dark text pairs meet 4.5:1 contrast',()=>{
  const css=fs.readFileSync(new URL('../src/theme.css',import.meta.url),'utf8');
  const blocks=css.match(/:root[^{}]*\{[^}]*\}/g);
  let light={};
  for(const block of blocks){
    const tokens=Object.fromEntries([...block.matchAll(/(--[\w-]+):\s*(#[\da-f]{6})\s*;/gi)].map(m=>[m[1],m[2]]));
    const merged={...light,...tokens};
    for(const [front,back] of [['--ink','--surface'],['--muted','--surface'],['--muted','--bg'],['--on-primary','--primary']]){
      const [a,b]=[luminance(merged[front]),luminance(merged[back])].sort((x,y)=>y-x);
      assert((a+.05)/(b+.05)>=4.5,`${block.includes('dark')?'dark':'light'} ${front}/${back}`);
    }
    light=merged;
  }
});
