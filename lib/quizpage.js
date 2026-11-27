// The quiz page (README "The quiz"): app.psycheai.io/quiz#<code>, where a friend answers someone's "How well do you
// know me?" with no sign-in. Everything about the quiz is opened here, in the friend's browser, with the code after
// the # (which browsers never send): the server hands over only locked boxes (lib/quiz.js).
//
// One question at a time; a tap shows ✓ or ✗ straight away, and a wrong answer never shows the right one (PLAN.md).
// Their Psyche Card is blurred, and their character unnamed, until the end, when the full card is revealed: shown first,
// it gave answers away (the finale is their character; the card lists what drives them). Then the score, how it ranks among friends who took it, and the turnaround: the line to paste into Muse to make
// their own quiz, which carries their picks after the # so their own Muse can show only the answers they missed.
// The line is shown only after the score, and only once they tap for it.
//
// The locking matches bin/psyche.py's e2e_seal / e2e_open: keys are sha256("psyche|<purpose>|<code>"), and a box is
// { v: 'e2e1', n, c, t }: an HMAC-SHA256 stream for the text and an HMAC-SHA256 tag over it.

const { page, esc } = require('./theme');

const CSS = `
html{background:#5a2585}
html body{background:radial-gradient(120% 70% at 0% 0%,#a35fd6 0%,transparent 55%),radial-gradient(110% 70% at 100% 100%,#e0527f 0%,transparent 55%),linear-gradient(160deg,#4a1f73,#6e2f96 45%,#b23a74);min-height:100vh;color:var(--ink)}
html body main{padding-top:10px}
html body .brand{color:#fff}html body .brand svg{color:#fff!important}
html body .foot{color:rgba(255,255,255,.7)}html body .foot a{color:#fff}
.q-orbs{position:fixed;inset:0;pointer-events:none;overflow:hidden;z-index:0}
.q-orbs i{position:absolute;border-radius:50%;filter:blur(2px);opacity:.35;background:radial-gradient(circle at 30% 30%,#fff,rgba(255,255,255,0) 70%);animation:q-drift 14s ease-in-out infinite}
.q-orbs i:nth-child(1){width:120px;height:120px;left:-30px;top:18%}.q-orbs i:nth-child(2){width:70px;height:70px;right:8%;top:8%;animation-delay:-4s}.q-orbs i:nth-child(3){width:160px;height:160px;right:-50px;bottom:12%;animation-delay:-8s}
@keyframes q-drift{0%,100%{transform:translate(0,0)}50%{transform:translate(18px,-26px)}}
main>section{position:relative;z-index:1}
.q-glass{background:var(--alt);border-radius:26px;padding:18px;box-shadow:0 18px 50px rgba(30,5,50,.35);margin:14px 0}
.q-top{text-align:center;color:#fff;padding:6px 6px 0}
.q-kick{display:inline-block;font-size:.72rem;letter-spacing:.2em;text-transform:uppercase;font-weight:800;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.3);border-radius:999px;padding:.35rem .8rem}
.q-top h1{color:#fff;font-size:2.35rem;line-height:1.08;margin:14px 0 6px;letter-spacing:-.03em;text-shadow:0 4px 24px rgba(0,0,0,.18)}
.q-top p{margin:0;opacity:.92}
.q-cardwrap{position:relative;width:58%;max-width:14rem;margin:20px auto 6px}
.q-card{display:block;width:100%;border-radius:18px;box-shadow:0 22px 50px rgba(20,0,40,.45);transform:rotate(-4deg);animation:q-float 5s ease-in-out infinite}
.q-cardwrap.q-locked .q-card{filter:blur(16px) saturate(1.15)}
.q-cardwrap.q-locked{border-radius:18px}
.q-seal{position:absolute;inset:0;display:grid;place-content:center;justify-items:center;gap:8px;text-align:center;color:#fff;font-weight:800;text-shadow:0 2px 12px rgba(0,0,0,.35);transform:rotate(-4deg)}
.q-seal b{display:grid;place-items:center;width:58px;height:58px;border-radius:50%;background:rgba(255,255,255,.22);border:1.5px solid rgba(255,255,255,.5);font-size:1.6rem;backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)}
.q-seal span{font-size:.92rem;line-height:1.3;padding:0 12px}
.q-reveal{text-align:center}
.q-reveal .q-kick{background:var(--accent-soft);border-color:transparent;color:var(--accent)}
.q-reveal h2{margin:10px 0 2px;font-size:1.5rem;letter-spacing:-.02em}
.q-reveal p{margin:0;color:var(--soft)}
.q-reveal img{display:block;width:78%;max-width:19rem;margin:16px auto 4px;border-radius:18px;box-shadow:0 18px 44px rgba(30,5,50,.35);animation:q-unblur 1.6s cubic-bezier(.2,.8,.2,1) both}
@keyframes q-unblur{0%{filter:blur(18px);transform:scale(.9) rotate(-4deg);opacity:.6}60%{filter:blur(4px)}100%{filter:blur(0);transform:none;opacity:1}}
.q-cardwrap:after{content:"✨";position:absolute;right:-14px;top:-12px;font-size:1.6rem;animation:q-twinkle 2.4s ease-in-out infinite}
@keyframes q-float{0%,100%{transform:rotate(-4deg) translateY(0)}50%{transform:rotate(-2deg) translateY(-8px)}}
@keyframes q-twinkle{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(.7);opacity:.6}}
.q-proof{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;margin:14px 0 0}
.q-proof span{background:rgba(255,255,255,.95);color:#4a1f73;font-weight:700;font-size:.85rem;border-radius:999px;padding:.35rem .8rem;box-shadow:0 6px 16px rgba(30,5,50,.2)}
.q-lead{margin:0 0 14px;color:var(--soft);font-size:.95rem}
.q-label{display:block;font-weight:800;margin:0 0 8px}
.q-glass input[type=text]{font-size:1.05rem;padding:.85rem 1rem;border-radius:16px}
.q-switch{display:flex;align-items:center;gap:12px;margin:14px 0 4px;font-size:.93rem;cursor:pointer;-webkit-tap-highlight-color:transparent}
.q-switch input{position:absolute;opacity:0;width:1px;height:1px}
.q-switch b{flex:none;position:relative;width:46px;height:28px;border-radius:999px;background:var(--line);transition:background .2s}
.q-switch b:after{content:"";position:absolute;left:3px;top:3px;width:22px;height:22px;border-radius:50%;background:#fff;box-shadow:0 2px 6px rgba(0,0,0,.25);transition:transform .2s}
.q-switch input:checked+b{background:var(--accent)}.q-switch input:checked+b:after{transform:translateX(18px)}
.q-switch input:focus-visible+b{outline:3px solid var(--accent-soft);outline-offset:2px}
.q-cta{position:relative;overflow:hidden;font-size:1.1rem!important;padding:1rem!important;margin-top:16px;box-shadow:0 12px 28px rgba(160,40,110,.35)}
.q-cta:after{content:"";position:absolute;top:0;left:-60%;width:40%;height:100%;background:linear-gradient(100deg,transparent,rgba(255,255,255,.45),transparent);animation:q-shine 2.8s ease-in-out infinite}
@keyframes q-shine{0%,60%{left:-60%}100%{left:130%}}
.q-lock{color:var(--soft);font-size:.82rem;text-align:center;margin:12px 0 0}
.q-hud{display:flex;align-items:center;justify-content:space-between;color:#fff;font-weight:800;margin:4px 2px 10px}
.q-hud span{background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.28);border-radius:999px;padding:.3rem .75rem;font-size:.9rem;transition:transform .2s}
.q-hud span.pop{transform:scale(1.18)}
.q-steps{display:flex;gap:5px;margin:0 2px 12px}.q-steps i{flex:1;height:7px;border-radius:9px;background:rgba(255,255,255,.25);transition:background .3s}
.q-steps i.y{background:#7ef0b0}.q-steps i.n{background:#ff9fbf}.q-steps i.now{background:#fff}
.q-step{font-size:.75rem;color:var(--soft);font-weight:800;letter-spacing:.12em;text-transform:uppercase;margin:0 0 8px}
.q-chip{display:inline-block;margin-left:6px;padding:.15rem .55rem;border-radius:999px;background:var(--accent-soft);color:var(--accent);letter-spacing:.04em}
.q-chip.hard{background:#fde4ee;color:#b0245d}.q-chip.finale{background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#fff}
.q-q{font-size:1.4rem;font-weight:800;line-height:1.28;margin:0 0 16px;letter-spacing:-.01em}
.q-opts{display:flex;flex-direction:column;gap:10px}
.q-opts button{display:flex;align-items:center;gap:12px;background:var(--alt);color:var(--ink);border:2px solid var(--line);border-radius:18px;text-align:left;padding:.9rem 1rem;font-weight:650;font-size:1rem;line-height:1.3;transition:transform .12s,border-color .2s,background .2s;animation:q-in .35s both}
.q-opts button:nth-child(2){animation-delay:.05s}.q-opts button:nth-child(3){animation-delay:.1s}.q-opts button:nth-child(4){animation-delay:.15s}
.q-opts button:active{transform:scale(.97)}
.q-opts button i{flex:none;display:grid;place-items:center;width:30px;height:30px;border-radius:10px;background:var(--accent-soft);color:var(--accent);font-style:normal;font-weight:800;font-size:.85rem}
.q-opts button[disabled]{cursor:default;opacity:.45}
.q-opts button.right{opacity:1;border-color:#1f9d5c;background:#e3f7ec;color:#0f4d2c;animation:q-pop .45s}.q-opts button.right i{background:#1f9d5c;color:#fff}
.q-opts button.wrong{opacity:1;border-color:#d23c74;background:#fde8f0;color:#7a1238;animation:q-shake .45s}.q-opts button.wrong i{background:#d23c74;color:#fff}
@keyframes q-in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
@keyframes q-pop{0%{transform:scale(1)}40%{transform:scale(1.05)}100%{transform:scale(1)}}
@keyframes q-shake{0%,100%{transform:translateX(0)}20%,60%{transform:translateX(-7px)}40%,80%{transform:translateX(7px)}}
.q-said{min-height:1.8rem;margin:14px 0 0;font-weight:800;font-size:1.08rem;text-align:center}
.q-said.ok{color:#1f9d5c}.q-said.no{color:#d23c74}
.q-slide{animation:q-slide .35s both}@keyframes q-slide{from{opacity:0;transform:translateX(24px)}to{opacity:1;transform:none}}
.q-res{text-align:center}
.q-ring{position:relative;width:170px;height:170px;margin:4px auto 10px}
.q-ring svg{width:100%;height:100%;transform:rotate(-90deg)}.q-ring circle{fill:none;stroke-width:14}.q-ring .bg{stroke:var(--accent-soft)}
.q-ring .fg{stroke:url(#q-grad);stroke-linecap:round;transition:stroke-dashoffset 1.4s cubic-bezier(.2,.8,.2,1)}
.q-ring div{position:absolute;inset:0;display:grid;place-content:center}
.q-score{font-size:2.9rem;font-weight:900;line-height:1;color:var(--ink);letter-spacing:-.03em}
.q-ring small{display:block;color:var(--soft);font-weight:700;margin-top:4px}
.q-tierrow{margin:4px 0 6px}.q-tier-e{font-size:1.45rem;margin-right:6px}
.q-tier{font-size:1.45rem;font-weight:900;letter-spacing:-.02em;background:linear-gradient(135deg,var(--accent),var(--accent-2));-webkit-background-clip:text;background-clip:text;color:transparent}
.q-badge{display:inline-block;position:relative;overflow:hidden;background:linear-gradient(135deg,#f7b733,#fc4a8a);color:#fff;border-radius:999px;padding:.4rem 1rem;font-weight:800;font-size:.95rem;margin:10px 0 0;box-shadow:0 8px 20px rgba(252,74,138,.35)}
.q-badge:after{content:"";position:absolute;top:0;left:-60%;width:40%;height:100%;background:linear-gradient(100deg,transparent,rgba(255,255,255,.6),transparent);animation:q-shine 2.4s ease-in-out infinite}
.q-marks{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin:14px 0 0}
.q-marks span{display:inline-grid;place-items:center;width:32px;height:32px;border-radius:11px;font-weight:900;font-size:.85rem;animation:q-in .3s both}
.q-marks .y{background:#e3f7ec;color:#1f9d5c}.q-marks .n{background:#fde8f0;color:#d23c74}
.q-mystery{display:flex;align-items:center;gap:12px;text-align:left;background:linear-gradient(135deg,var(--accent-soft),transparent);border:1.5px dashed var(--accent);border-radius:18px;padding:12px 14px;margin:0 0 12px}
.q-mystery b{font-size:1.6rem}.q-mystery p{margin:0;font-size:.95rem}
.q-board{list-style:none;padding:0;margin:0}.q-board li{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:14px;margin:4px 0;font-weight:650}
.q-board li em{font-style:normal;width:1.8rem;text-align:center;font-size:1.1rem}.q-board li span{flex:1}.q-board li strong{font-weight:900}
.q-board li.me{background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#fff}
.q-title{display:flex;align-items:center;gap:8px;font-weight:900;font-size:1.05rem;margin:0 0 4px}
.q-line{font:600 .9rem/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--accent-soft);border-radius:14px;padding:12px;word-break:break-all;margin:10px 0}
.q-gap{height:10px}
.q-fx{position:fixed;inset:0;pointer-events:none;z-index:50}
[hidden]{display:none!important}
@media (prefers-color-scheme:dark){.q-opts button.right{background:#10331f;color:#c4f5d8}.q-opts button.wrong{background:#3c1426;color:#ffd3e3}.q-marks .y{background:#10331f}.q-marks .n{background:#3c1426}.q-chip.hard{background:#3c1426;color:#ffb3cd}.q-proof span{background:rgba(31,25,38,.92);color:#f1ebf5}}
@media (prefers-reduced-motion:reduce){*,*:before,*:after{animation:none!important;transition:none!important}}
`;

// The page's locking, apart so the selftest can run it against bin/psyche.py's (README "The quiz").
const CRYPTO = String.raw`
var te=new TextEncoder(),td=new TextDecoder();
function b64e(u){var s='';for(var i=0;i<u.length;i++)s+=String.fromCharCode(u[i]);return btoa(s).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');}
function b64d(t){t=String(t).replace(/-/g,'+').replace(/_/g,'/');while(t.length%4)t+='=';var s=atob(t),u=new Uint8Array(s.length);for(var i=0;i<s.length;i++)u[i]=s.charCodeAt(i);return u;}
function cat(){var n=0,i,a=arguments;for(i=0;i<a.length;i++)n+=a[i].length;var o=new Uint8Array(n),k=0;for(i=0;i<a.length;i++){o.set(a[i],k);k+=a[i].length;}return o;}
function sha(text){return crypto.subtle.digest('SHA-256',te.encode(text)).then(function(b){return new Uint8Array(b);});}
function hmac(key,data){return crypto.subtle.importKey('raw',key,{name:'HMAC',hash:'SHA-256'},false,['sign']).then(function(k){return crypto.subtle.sign('HMAC',k,data);}).then(function(b){return new Uint8Array(b);});}
function keyFor(purpose,code){return sha('psyche|'+purpose+'|'+code);}
function stream(enc,nonce,size){var parts=[],n=Math.ceil(size/32),p=Promise.resolve();
 for(var i=0;i<n;i++)(function(i){var c=new Uint8Array(8);var v=i;for(var j=7;j>=0;j--){c[j]=v&255;v=Math.floor(v/256);}p=p.then(function(){return hmac(enc,cat(nonce,c)).then(function(b){parts.push(b);});});})(i);
 return p.then(function(){return cat.apply(null,parts).slice(0,size);});}
function open(box,key){if(!box||box.v!=='e2e1')return Promise.resolve(null);var nonce=b64d(box.n),ct=b64d(box.c),tag=b64d(box.t),encK,macK;
 return hmac(key,te.encode('psyche-e2e-mac')).then(function(m){macK=m;return hmac(macK,cat(te.encode('e2e1'),nonce,ct));}).then(function(want){
  if(want.length!==tag.length)return null;var d=0;for(var i=0;i<want.length;i++)d|=want[i]^tag[i];if(d)return null;
  return hmac(key,te.encode('psyche-e2e-enc')).then(function(e){encK=e;return stream(encK,nonce,ct.length);}).then(function(s){var out=new Uint8Array(ct.length);for(var i=0;i<ct.length;i++)out[i]=ct[i]^s[i];return JSON.parse(td.decode(out));});
 }).catch(function(){return null;});}
function seal(value,key){var data=te.encode(JSON.stringify(value)),nonce=crypto.getRandomValues(new Uint8Array(16)),encK,macK,ct;
 return hmac(key,te.encode('psyche-e2e-enc')).then(function(e){encK=e;return stream(encK,nonce,data.length);}).then(function(s){ct=new Uint8Array(data.length);for(var i=0;i<data.length;i++)ct[i]=data[i]^s[i];
  return hmac(key,te.encode('psyche-e2e-mac'));}).then(function(m){macK=m;return hmac(macK,cat(te.encode('e2e1'),nonce,ct));}).then(function(t){return {v:'e2e1',n:b64e(nonce),c:b64e(ct),t:b64e(t)};});}
function hex(u){return Array.prototype.map.call(u,function(x){return ('0'+x.toString(16)).slice(-2);}).join('');}
`;

const JS = '(function(){\n' + CRYPTO + String.raw`
var $=function(id){return document.getElementById(id);};
function store(k,v){try{if(v===undefined)return JSON.parse(localStorage.getItem(k)||'null');localStorage.setItem(k,JSON.stringify(v));}catch(e){return null;}}
function show(id){['q-wait','q-intro','q-ask','q-done','q-err'].forEach(function(x){$(x).hidden=x!==id;});window.scrollTo(0,0);}
function fail(msg){$('q-err-msg').textContent=msg;show('q-err');}
var still=window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches;
function pickOne(xs){return xs[Math.floor(Math.random()*xs.length)];}
// A short burst of confetti from a point, drawn on one canvas over the page; nothing with reduced motion.
function burst(x,y,n){if(still)return;var c=$('q-fx'),g=c.getContext('2d'),dpr=window.devicePixelRatio||1;c.width=innerWidth*dpr;c.height=innerHeight*dpr;g.scale(dpr,dpr);
 var cols=['#ffd166','#ff6b9a','#7ef0b0','#a98bff','#ffffff','#5ad1ff'],ps=[];for(var i=0;i<n;i++){var a=Math.random()*Math.PI*2,v=3+Math.random()*7;ps.push({x:x,y:y,vx:Math.cos(a)*v,vy:Math.sin(a)*v-4,r:3+Math.random()*4,c:pickOne(cols),t:0,s:Math.random()*6});}
 var t0=null;function step(t){if(!t0)t0=t;var k=(t-t0)/1000;g.clearRect(0,0,innerWidth,innerHeight);
  ps.forEach(function(p){p.vy+=.35;p.x+=p.vx;p.y+=p.vy;p.s+=.2;g.save();g.globalAlpha=Math.max(0,1-k/1.4);g.fillStyle=p.c;g.translate(p.x,p.y);g.rotate(p.s);g.fillRect(-p.r,-p.r/2,p.r*2,p.r);g.restore();});
  if(k<1.4)requestAnimationFrame(step);else g.clearRect(0,0,innerWidth,innerHeight);}requestAnimationFrame(step);}

var m=/^#([A-Za-z0-9_-]{22})/.exec(location.hash||'');
if(!m||!window.crypto||!crypto.subtle){fail(m?'This browser can\'t open the quiz. Try opening the link in Safari or Chrome.':'This quiz link isn\'t complete. Ask your friend to send it again.');return;}
var code=m[1],id,quiz,data,at=0,picks=[],right=0,streak=0,mine=null;
keyFor('quiz-id',code).then(function(k){id=hex(k);return fetch('/quiz/data/'+id,{cache:'no-store'});})
.then(function(r){return r.json();}).then(function(d){if(d.error)throw new Error(d.error);data=d;return keyFor('quiz',code).then(function(k){return open(d.box,k);});})
.then(function(q){if(!q||!q.questions||!q.questions.length)throw new Error('This quiz couldn\'t be opened with this link. Ask your friend to send it again.');quiz=q;intro();})
.catch(function(e){fail(e&&e.message||'This quiz couldn\'t be loaded. Check your connection and reload.');});

function nm(){return quiz.name||'your friend';}
function hasCard(){return Boolean(quiz.card&&/^data:image\/(jpeg|png);base64,/.test(quiz.card));}
function n(){return quiz.questions.length;}
function intro(){
 document.title='How well do you know '+nm()+'?';
 $('q-title').textContent='How well do you know '+nm()+'?';
 $('q-sub').textContent=n()+' questions. See straight away if you\'re right, but never the answer.';
 // Their card stays blurred, and their character unnamed, until the end: it would give answers away (README "The quiz").
 if(hasCard()){$('q-card').src=quiz.card;$('q-cardwrap').hidden=false;$('q-seal-t').textContent=nm()+'\'s Psyche Card, revealed at the end';$('q-char').textContent='Answer to unlock '+nm()+'\'s Psyche Card';}
 // Who's played so far, as numbers only: names stay on the board, for those who chose to show them.
 var proof=[];if(data.count)proof.push('🔥 '+data.count+(data.count===1?' friend has played':' friends have played'));
 if(data.board&&data.board.length)proof.push('🏆 Top score '+data.board[0].s+'/'+n());else proof.push('🥇 Be the first to play');
 $('q-proof').innerHTML='';proof.forEach(function(t){var s=document.createElement('span');s.textContent=t;$('q-proof').appendChild(s);});
 $('q-lead').textContent='Think you know '+nm()+'? Prove it.';
 var was=store('quiz:'+id);
 if(was&&was.result){picks=was.picks||[];right=was.s;mine=was.result;done(true);return;}
 show('q-intro');}
$('q-go').onclick=function(){var v=$('q-name').value.trim();if(!v){$('q-name').focus();$('q-name').style.borderColor='var(--accent)';return;}at=0;picks=[];right=0;streak=0;ask();};
$('q-name').onkeydown=function(e){if(e.key==='Enter')$('q-go').click();};
var KIND={'year':['📅 The year',''],'numbers':['📊 By the numbers',''],'rather':['⚖️ Would they rather',''],'deep':['💭 Deep',''],'hard':['🔥 Hard','hard'],'finale':['✨ Finale','finale'],'warm-up':['Warm-up','']};
function hud(){$('q-pts').textContent='⭐ '+right;$('q-streak').textContent=streak>1?'🔥 '+streak+' in a row':'🔥 '+streak;
 var st=$('q-steps');st.innerHTML='';for(var i=0;i<n();i++){var d=document.createElement('i');if(i<picks.length)d.className=picks[i]===quiz.questions[i].a?'y':'n';else if(i===at)d.className='now';st.appendChild(d);}}
function ask(){var q=quiz.questions[at];show('q-ask');hud();
 var card=$('q-card-ask');card.classList.remove('q-slide');void card.offsetWidth;card.classList.add('q-slide');
 var kd=KIND[q.k]||null;$('q-step').innerHTML='';$('q-step').appendChild(document.createTextNode('Question '+(at+1)+' of '+n()));
 if(kd){var c=document.createElement('span');c.className='q-chip '+kd[1];c.textContent=kd[0];$('q-step').appendChild(c);}
 $('q-q').textContent=q.q;$('q-said').textContent='';$('q-said').className='q-said';
 var box=$('q-opts');box.innerHTML='';
 q.o.forEach(function(o,i){var b=document.createElement('button');b.type='button';var l=document.createElement('i');l.textContent='ABCD'[i];var t=document.createElement('span');t.textContent=o;b.appendChild(l);b.appendChild(t);b.onclick=function(){pick(i,b);};box.appendChild(b);});}
function pick(i,b){var q=quiz.questions[at],ok=i===q.a;picks.push(i);if(ok){right++;streak++;}else streak=0;
 [].forEach.call($('q-opts').children,function(x){x.disabled=true;});
 b.className=ok?'right':'wrong';
 // Right or wrong, never which one was right (PLAN.md).
 $('q-said').textContent=ok?pickOne(['✓ You know '+nm()+' ✨','✓ Spot on!','✓ Nailed it','✓ Bestie move']):pickOne(['✗ Not quite','✗ Not that one','✗ Plot twist']);$('q-said').className='q-said '+(ok?'ok':'no');
 if(ok){var r=b.getBoundingClientRect();burst(r.left+r.width/2,r.top+r.height/2,streak>2?70:36);}else if(navigator.vibrate){try{navigator.vibrate(60);}catch(e){}}
 hud();if(ok){$('q-pts').classList.add('pop');setTimeout(function(){$('q-pts').classList.remove('pop');},250);}
 setTimeout(function(){at++;if(at<n())ask();else send();},1150);}
function send(){show('q-wait');$('q-wait-msg').textContent='Adding up your score…';var name=$('q-name').value.trim().slice(0,30),shown=$('q-show').checked;
 Promise.all([keyFor('quiz-answer',code).then(function(k){return seal({name:name,p:picks},k);}),shown?keyFor('quiz-name',code).then(function(k){return seal({name:name},k);}):null])
 .then(function(b){return fetch('/quiz/answer/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({s:right,box:b[0],name:b[1]})});})
 .then(function(r){return r.json();}).then(function(r){if(r.error)throw new Error(r.error);mine=r;mine.me=name;store('quiz:'+id,{s:right,picks:picks,result:r});done(false);})
 .catch(function(e){fail(e&&e.message||'Your answers couldn\'t be sent. Check your connection and reload.');});}
function tier(p){return p===1?['Soulmate level','💞']:p>=.8?['Best friend energy','🫶']:p>=.6?['A real friend','🤝']:p>=.4?['Getting there','🌱']:['Total mystery','🕵️'];}
function done(again){var tot=n(),p=right/tot,t=tier(p);show('q-done');
 // The full card, revealed now that the quiz is over (the answers they missed stay hidden).
 if(hasCard()){var im=$('q-reveal-img');im.src=quiz.card;if(again)im.style.animation='none';$('q-reveal-h').textContent=nm()+'\'s Psyche Card';
  $('q-reveal-p').textContent=quiz.character?nm()+' is most like '+quiz.character+'.':'';$('q-reveal').hidden=false;}else $('q-reveal').hidden=true;
 $('q-score').textContent=right+'/'+tot;$('q-pct').textContent=Math.round(100*p)+'%';
 $('q-tier-e').textContent=t[1];$('q-tier').textContent=t[0];
 var fg=$('q-fg'),len=2*Math.PI*78;fg.style.strokeDasharray=len;fg.style.strokeDashoffset=len;setTimeout(function(){fg.style.strokeDashoffset=len*(1-p);},again?0:120);
 var before=mine.count-1;
 $('q-better').textContent=mine.better==null?'You\'re the first to take '+nm()+'\'s quiz.':mine.better===100?(before===1?'You beat the friend who took it before you.':'You beat every friend who took it before you.'):mine.better===0?(before===1?'The friend before you did at least as well. Time to catch up!':'Everyone before you did at least as well. Time to catch up!')
  :'You know '+nm()+' better than '+mine.better+'% of the '+(before===1?'friend':'friends')+' who took it before you.';
 $('q-badge').hidden=!(mine.top&&right>0);$('q-badge').textContent=mine.count>1?'🏆 Best friend':'🏆 Best friend, so far';
 var mk=$('q-marks');mk.innerHTML='';picks.forEach(function(x,i){var s=document.createElement('span'),ok=x===quiz.questions[i].a;s.className=ok?'y':'n';s.textContent=ok?'✓':'✗';s.style.animationDelay=(i*.05)+'s';mk.appendChild(s);});
 var missed=picks.filter(function(x,i){return x!==quiz.questions[i].a;}).length;
 $('q-myst').hidden=!missed;$('q-myst-who').textContent=nm();$('q-myst-n').textContent=missed===1?'1 answer is still a mystery.':missed+' answers are still a mystery.';
 $('q-turn').textContent=missed?'🔓 Unlock them: make your quiz in Muse':'Your turn: make your quiz in Muse';
 if(!again&&(p>=.8||(mine.top&&right>0)))setTimeout(function(){burst(innerWidth/2,innerHeight*.3,120);},700);
 board();}
function board(){var list=mine.board||[];if(list.length<2){$('q-board-box').hidden=true;return;}
 keyFor('quiz-name',code).then(function(k){return Promise.all(list.map(function(e){return e.name?open(e.name,k):null;}));}).then(function(names){
  var ul=$('q-board');ul.innerHTML='';var me=false;
  list.forEach(function(e,i){var li=document.createElement('li'),who=names[i]&&names[i].name?String(names[i].name).slice(0,30):'A friend';
   if(!me&&e.s===right&&i+1===mine.rank){li.className='me';who=String(mine.me||who)+' (you)';me=true;}
   var md=document.createElement('em'),a=document.createElement('span'),b=document.createElement('strong');md.textContent=['🥇','🥈','🥉'][i]||(i+1)+'.';a.textContent=who;b.textContent=e.s+'/'+n();
   li.appendChild(md);li.appendChild(a);li.appendChild(b);ul.appendChild(li);});
  $('q-rank').textContent='You\'re number '+mine.rank+' of '+mine.count+'.';$('q-board-box').hidden=false;});}
function link(){var base=location.origin+'/quiz#'+code;return base;}
function installLine(){var o=location.origin,short=o==='https://app.psycheai.io'?'https://psycheai.io/skill':o+'/install';
 return 'Install '+short+' and make my quiz for '+String(nm()).slice(0,30)+': '+link()+'.'+picks.join('');}
$('q-share').onclick=function(){var t='I got '+right+'/'+n()+' on how well I know '+nm()+' '+tier(right/n())[1]+' Can you beat me?';
 if(navigator.share){navigator.share({text:t,url:link()}).catch(function(){});}else copy(t+' '+link(),$('q-share'));};
$('q-turn').onclick=function(){$('q-line').textContent=installLine();$('q-turn-box').hidden=false;$('q-turn').hidden=true;};
$('q-copy').onclick=function(){copy($('q-line').textContent,$('q-copy'));};
function copy(text,btn){var was=btn.textContent;function ok(){btn.textContent='Copied ✓';setTimeout(function(){btn.textContent=was;},1600);}
 if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(text).then(ok,function(){});else{var r=document.createRange();r.selectNodeContents($('q-line'));var s=getSelection();s.removeAllRanges();s.addRange(r);try{document.execCommand('copy');ok();}catch(e){}}}
})();
`;

const BODY = `
<div class="q-orbs" aria-hidden="true"><i></i><i></i><i></i></div>
<canvas id="q-fx" class="q-fx" aria-hidden="true"></canvas>
<section id="q-wait" class="q-glass" style="text-align:center"><p id="q-wait-msg" class="muted" style="margin:0">Opening the quiz…</p></section>
<section id="q-err" class="q-glass" hidden><p id="q-err-msg" class="error" style="margin:0"></p></section>
<section id="q-intro" hidden>
  <div class="q-top"><span class="q-kick">PsycheAI quiz</span><h1 id="q-title">How well do you know your friend?</h1><p id="q-char"></p></div>
  <div id="q-cardwrap" class="q-cardwrap q-locked" hidden><img id="q-card" class="q-card" alt="Their Psyche Card, blurred until the end"><div class="q-seal"><b>🔒</b><span id="q-seal-t"></span></div></div>
  <div id="q-proof" class="q-proof"></div>
  <div class="q-glass"><p id="q-lead" class="q-title" style="margin-bottom:2px"></p><p id="q-sub" class="q-lead"></p>
    <label class="q-label" for="q-name">Your first name</label>
    <input type="text" id="q-name" maxlength="30" autocomplete="given-name" placeholder="So they know it's you">
    <label class="q-switch"><input type="checkbox" id="q-show" checked><b></b><span>Show my name on the leaderboard</span></label>
    <button type="button" id="q-go" class="q-cta">Let's play →</button>
    <p class="q-lock">🔒 Only your friend sees your answers. PsycheAI can't read your name or your answers.</p></div>
</section>
<section id="q-ask" hidden>
  <div class="q-hud"><span id="q-pts">⭐ 0</span><span id="q-streak">🔥 0</span></div>
  <div id="q-steps" class="q-steps"></div>
  <div id="q-card-ask" class="q-glass"><p id="q-step" class="q-step"></p>
    <p id="q-q" class="q-q"></p><div id="q-opts" class="q-opts"></div><p id="q-said" class="q-said"></p></div>
</section>
<section id="q-done" hidden>
  <div class="q-glass q-res"><p class="q-step" style="margin-bottom:6px">Your score</p>
    <div class="q-ring"><svg viewBox="0 0 180 180" aria-hidden="true"><defs><linearGradient id="q-grad" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#7b3fa0"/><stop offset="1" stop-color="#e0527f"/></linearGradient></defs><circle class="bg" cx="90" cy="90" r="78"/><circle id="q-fg" class="fg" cx="90" cy="90" r="78"/></svg>
      <div><span id="q-score" class="q-score"></span><small id="q-pct"></small></div></div>
    <p class="q-tierrow"><span id="q-tier-e" class="q-tier-e"></span><span id="q-tier" class="q-tier"></span></p><p id="q-better" style="margin:0"></p>
    <span id="q-badge" class="q-badge" hidden></span><div id="q-marks" class="q-marks"></div></div>
  <div id="q-reveal" class="q-glass q-reveal" hidden><span class="q-kick">🔓 Unlocked</span><h2 id="q-reveal-h"></h2><p id="q-reveal-p"></p><img id="q-reveal-img" alt="Their Psyche Card"></div>
  <div id="q-board-box" class="q-glass" hidden><p class="q-title">🏆 Leaderboard</p><p id="q-rank" class="muted" style="margin:0 0 6px"></p><ul id="q-board" class="q-board"></ul></div>
  <div class="q-glass">
    <div id="q-myst" class="q-mystery" hidden><b>🔒</b><p><strong id="q-myst-n"></strong> Make your own quiz to see what <span id="q-myst-who"></span> really said.</p></div>
    <button type="button" id="q-turn" class="q-cta">Your turn: make your quiz in Muse</button>
    <div id="q-turn-box" hidden><p style="margin:0">Paste this into your Muse app. PsycheAI writes your quiz from your own Instagram, and making it shows you the answers you missed here.</p>
      <div id="q-line" class="q-line"></div><button type="button" id="q-copy">Copy</button></div>
    <div class="q-gap"></div><button type="button" id="q-share" class="ghost">📣 Challenge a friend</button></div>
</section>`;

let cached = null;
function page_() {
  if (cached) return cached;
  cached = page('How well do you know me?', BODY, { head: `<style>${CSS}</style><meta name="description" content="${esc('A PsycheAI quiz: how well do you know your friend?')}">` })
    .replace('</main></body>', () => `</main><script>${JS.replace(/<\//g, '<\\/')}</script></body>`);
  return cached;
}

module.exports = { page: page_, CSS, JS, CRYPTO };
