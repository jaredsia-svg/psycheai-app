// The quiz page (README "The quiz"): app.psycheai.io/quiz#<code>, where a friend answers someone's "How well do you
// know me?" with no sign-in. Everything about the quiz is opened here, in the friend's browser, with the code after
// the # (which browsers never send): the server hands over only locked boxes (lib/quiz.js).
//
// One question at a time; a tap shows ✓ or ✗ straight away, and a wrong answer never shows the right one (PLAN.md).
// Then the score, how it ranks among friends who took it, and the turnaround: the line to paste into Muse to make
// their own quiz, which carries their picks after the # so their own Muse can show only the answers they missed.
// The line is shown only after the score, and only once they tap for it.
//
// The locking matches bin/psyche.py's e2e_seal / e2e_open: keys are sha256("psyche|<purpose>|<code>"), and a box is
// { v: 'e2e1', n, c, t }: an HMAC-SHA256 stream for the text and an HMAC-SHA256 tag over it.

const { page, esc } = require('./theme');

const CSS = `
.q-hero{text-align:center;padding:18px 18px 22px}
.q-hero h1{font-size:1.75rem}
.q-card{display:block;width:62%;max-width:15rem;margin:14px auto 4px;border-radius:18px;box-shadow:0 10px 30px rgba(40,10,60,.25)}
.q-step{font-size:.8rem;color:var(--soft);font-weight:600;letter-spacing:.06em;text-transform:uppercase;margin:4px 0 8px}
.q-prog{height:6px;background:var(--accent-soft);border-radius:9px;overflow:hidden;margin:0 0 14px}.q-prog i{display:block;height:100%;width:0;background:var(--accent);transition:width .3s}
.q-q{font-size:1.25rem;font-weight:700;line-height:1.3;margin:0 0 14px}
.q-opts{display:flex;flex-direction:column;gap:8px}
.q-opts button{background:var(--alt);color:var(--ink);border:1.5px solid var(--line);border-radius:16px;text-align:left;padding:.85rem 1rem;font-weight:600;line-height:1.3}
.q-opts button[disabled]{cursor:default;opacity:.55}
.q-opts button.right{opacity:1;border-color:#1f8a52;background:#e6f4ec;color:#14532d}
.q-opts button.wrong{opacity:1;border-color:#c2366d;background:#fcebf2;color:#7a1238}
.q-said{min-height:1.6rem;margin:12px 0 0;font-weight:700;text-align:center}
.q-said.ok{color:#1f8a52}.q-said.no{color:#c2366d}
.q-score{font-size:3.4rem;font-weight:800;line-height:1;margin:6px 0 4px;color:var(--accent)}
.q-badge{display:inline-block;background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#fff;border-radius:999px;padding:.3rem .9rem;font-weight:700;font-size:.9rem;margin:8px 0 0}
.q-marks{display:flex;flex-wrap:wrap;gap:6px;justify-content:center;margin:12px 0 0}
.q-marks span{display:inline-grid;place-items:center;width:30px;height:30px;border-radius:50%;font-weight:800;font-size:.9rem}
.q-marks .y{background:#e6f4ec;color:#1f8a52}.q-marks .n{background:#fcebf2;color:#c2366d}
.q-board{list-style:none;padding:0;margin:0}.q-board li{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--line)}.q-board li:last-child{border:0}
.q-board li.me{font-weight:800;color:var(--accent)}
.q-line{font:600 .95rem/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--accent-soft);border-radius:12px;padding:12px;word-break:break-all;margin:10px 0}
.q-row{display:flex;gap:8px;align-items:flex-start;margin:12px 0 0;font-size:.95rem}.q-row input{width:auto;margin-top:4px}
.q-gap{height:10px}
[hidden]{display:none!important}
@media (prefers-color-scheme:dark){.q-opts button.right{background:#12301f;color:#bff0d2}.q-opts button.wrong{background:#3a1424;color:#ffd0e1}.q-marks .y{background:#12301f}.q-marks .n{background:#3a1424}}
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

var m=/^#([A-Za-z0-9_-]{22})/.exec(location.hash||'');
if(!m||!window.crypto||!crypto.subtle){fail(m?'This browser can\'t open the quiz. Try opening the link in Safari or Chrome.':'This quiz link isn\'t complete. Ask your friend to send it again.');return;}
var code=m[1],id,quiz,data,at=0,picks=[],right=0,mine=null;
keyFor('quiz-id',code).then(function(k){id=hex(k);return fetch('/quiz/data/'+id,{cache:'no-store'});})
.then(function(r){return r.json();}).then(function(d){if(d.error)throw new Error(d.error);data=d;return keyFor('quiz',code).then(function(k){return open(d.box,k);});})
.then(function(q){if(!q||!q.questions||!q.questions.length)throw new Error('This quiz couldn\'t be opened with this link. Ask your friend to send it again.');quiz=q;intro();})
.catch(function(e){fail(e&&e.message||'This quiz couldn\'t be loaded. Check your connection and reload.');});

function nm(){return quiz.name||'your friend';}
function intro(){
 document.title='How well do you know '+nm()+'?';
 $('q-title').textContent='How well do you know '+nm()+'?';
 $('q-sub').textContent=quiz.questions.length+' questions about '+nm()+'. You see straight away if you got each one right, but never the right answer.';
 if(quiz.character)$('q-char').textContent=nm()+' got '+quiz.character+' on PsycheAI.';
 if(quiz.card&&/^data:image\/(jpeg|png);base64,/.test(quiz.card)){$('q-card').src=quiz.card;$('q-card').hidden=false;}
 var was=store('quiz:'+id);
 if(was&&was.result){picks=was.picks||[];right=was.s;mine=was.result;done();return;}
 show('q-intro');}
$('q-go').onclick=function(){var n=$('q-name').value.trim();if(!n){$('q-name').focus();return;}at=0;picks=[];right=0;ask();};
function ask(){var q=quiz.questions[at];show('q-ask');
 $('q-step').textContent='Question '+(at+1)+' of '+quiz.questions.length;
 $('q-bar').style.width=Math.round(100*at/quiz.questions.length)+'%';
 $('q-q').textContent=q.q;$('q-said').textContent='';$('q-said').className='q-said';
 var box=$('q-opts');box.innerHTML='';
 q.o.forEach(function(o,i){var b=document.createElement('button');b.type='button';b.textContent=o;b.onclick=function(){pick(i,b);};box.appendChild(b);});}
function pick(i,b){var q=quiz.questions[at],ok=i===q.a;picks.push(i);if(ok)right++;
 [].forEach.call($('q-opts').children,function(x){x.disabled=true;});
 b.className=ok?'right':'wrong';$('q-said').textContent=ok?'✓ You know '+nm():'✗ Not quite';$('q-said').className='q-said '+(ok?'ok':'no');
 setTimeout(function(){at++;if(at<quiz.questions.length)ask();else send();},1100);}
function send(){show('q-wait');var name=$('q-name').value.trim().slice(0,30),shown=$('q-show').checked;
 Promise.all([keyFor('quiz-answer',code).then(function(k){return seal({name:name,p:picks},k);}),shown?keyFor('quiz-name',code).then(function(k){return seal({name:name},k);}):null])
 .then(function(b){return fetch('/quiz/answer/'+id,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({s:right,box:b[0],name:b[1]})});})
 .then(function(r){return r.json();}).then(function(r){if(r.error)throw new Error(r.error);mine=r;mine.me=name;store('quiz:'+id,{s:right,picks:picks,result:r});done();})
 .catch(function(e){fail(e&&e.message||'Your answers couldn\'t be sent. Check your connection and reload.');});}
function done(){var n=quiz.questions.length;show('q-done');
 $('q-score').textContent=right+'/'+n;
 var before=mine.count-1;
 $('q-better').textContent=mine.better==null?'You\'re the first to take '+nm()+'\'s quiz.':mine.better===0?(before===1?'The friend who took it before you scored higher.':'The friends who took it before you scored higher. Time to catch up!')
  :'You know '+nm()+' better than '+mine.better+'% of the '+(before===1?'friend':'friends')+' who took it before you.';
 $('q-badge').hidden=!(mine.top&&right>0);$('q-badge').textContent=mine.count>1?'🏆 Best friend':'🏆 Best friend, so far';
 var mk=$('q-marks');mk.innerHTML='';picks.forEach(function(p,i){var s=document.createElement('span'),ok=p===quiz.questions[i].a;s.className=ok?'y':'n';s.textContent=ok?'✓':'✗';mk.appendChild(s);});
 board();}
function board(){var list=mine.board||[];if(list.length<2){$('q-board-box').hidden=true;return;}
 keyFor('quiz-name',code).then(function(k){return Promise.all(list.map(function(e){return e.name?open(e.name,k):null;}));}).then(function(names){
  var ul=$('q-board');ul.innerHTML='';var me=false;
  list.forEach(function(e,i){var li=document.createElement('li'),who=names[i]&&names[i].name?String(names[i].name).slice(0,30):'A friend';
   if(!me&&e.s===right&&i+1===mine.rank){li.className='me';who=String(mine.me||who)+' (you)';me=true;}
   var a=document.createElement('span'),b=document.createElement('span');a.textContent=(i+1)+'. '+who;b.textContent=e.s+'/'+quiz.questions.length;li.appendChild(a);li.appendChild(b);ul.appendChild(li);});
  $('q-rank').textContent='You\'re number '+mine.rank+' of '+mine.count+'.';$('q-board-box').hidden=false;});}
function link(){var base=location.origin+'/quiz#'+code;return base;}
function installLine(){var o=location.origin,short=o==='https://app.psycheai.io'?'https://psycheai.io/skill':o+'/install';
 return 'Install '+short+' and make my quiz for '+String(nm()).slice(0,30)+': '+link()+'.'+picks.join('');}
$('q-share').onclick=function(){var t='I got '+right+'/'+quiz.questions.length+' on how well I know '+nm()+'. Can you beat me?';
 if(navigator.share){navigator.share({text:t,url:link()}).catch(function(){});}else copy(t+' '+link(),$('q-share'));};
$('q-turn').onclick=function(){$('q-line').textContent=installLine();$('q-turn-box').hidden=false;$('q-turn').hidden=true;};
$('q-copy').onclick=function(){copy($('q-line').textContent,$('q-copy'));};
function copy(text,btn){var was=btn.textContent;function ok(){btn.textContent='Copied';setTimeout(function(){btn.textContent=was;},1600);}
 if(navigator.clipboard&&navigator.clipboard.writeText)navigator.clipboard.writeText(text).then(ok,function(){});else{var r=document.createRange();r.selectNodeContents($('q-line'));var s=getSelection();s.removeAllRanges();s.addRange(r);try{document.execCommand('copy');ok();}catch(e){}}}
})();
`;

const BODY = `
<section id="q-wait" class="box q-hero"><p class="muted">Opening the quiz…</p></section>
<section id="q-err" class="box" hidden><p id="q-err-msg" class="error"></p></section>
<section id="q-intro" hidden>
  <div class="hero q-hero"><p class="kicker">PsycheAI quiz</p><h1 id="q-title">How well do you know your friend?</h1><p id="q-char"></p></div>
  <img id="q-card" class="q-card" alt="Their Psyche Card" hidden>
  <div class="box"><p id="q-sub" class="muted" style="margin-top:0"></p>
    <label for="q-name"><b>Your first name</b></label><div class="q-gap"></div>
    <input id="q-name" maxlength="30" autocomplete="given-name" placeholder="So they know who took it">
    <label class="q-row"><input type="checkbox" id="q-show"><span>Show my name to their other friends on the leaderboard</span></label>
    <div class="q-gap"></div><button type="button" id="q-go">Start</button>
    <p class="note">Only your friend sees your answers. PsycheAI can't read your name or your answers.</p></div>
</section>
<section id="q-ask" class="box" hidden>
  <p id="q-step" class="q-step"></p><div class="q-prog"><i id="q-bar"></i></div>
  <p id="q-q" class="q-q"></p><div id="q-opts" class="q-opts"></div><p id="q-said" class="q-said"></p>
</section>
<section id="q-done" hidden>
  <div class="box q-hero"><p class="kicker muted">Your score</p><div id="q-score" class="q-score"></div><p id="q-better" style="margin:6px 0 0"></p>
    <span id="q-badge" class="q-badge" hidden></span><div id="q-marks" class="q-marks"></div>
    <p class="note">The ones you missed stay a mystery, until you make your own quiz.</p></div>
  <div id="q-board-box" class="box" hidden><p class="lab">Leaderboard</p><p id="q-rank" class="muted" style="margin:0 0 6px"></p><ul id="q-board" class="q-board"></ul></div>
  <div class="box"><button type="button" id="q-turn">Your turn: make your quiz in Muse</button>
    <div id="q-turn-box" hidden><p style="margin:0">Paste this into your Muse app. PsycheAI writes your quiz from your own Instagram, and making it shows you the answers you missed here.</p>
      <div id="q-line" class="q-line"></div><button type="button" id="q-copy">Copy</button></div>
    <div class="q-gap"></div><button type="button" id="q-share" class="ghost">Share my score</button></div>
</section>`;

let cached = null;
function page_() {
  if (cached) return cached;
  cached = page('How well do you know me?', BODY, { head: `<style>${CSS}</style><meta name="description" content="${esc('A PsycheAI quiz: how well do you know your friend?')}">` })
    .replace('</main></body>', () => `</main><script>${JS.replace(/<\//g, '<\\/')}</script></body>`);
  return cached;
}

module.exports = { page: page_, CSS, JS, CRYPTO };
