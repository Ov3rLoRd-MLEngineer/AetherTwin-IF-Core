// Ajouté par le Hub en tête de chaque simulation servie (voir sims.with_hub_tools).
/* AetherTwin : pause et taille du cadre */(function(){
var paused=false,held=[],since=0,shift=0,raf=window.requestAnimationFrame.bind(window),
 st=window.setTimeout.bind(window),si=window.setInterval.bind(window),clock=performance.now.bind(performance);
performance.now=function(){return (paused?since:clock())-shift};
window.requestAnimationFrame=function(cb){return raf(function(t){if(paused){held.push(cb);return}cb(t-shift)})};
window.setInterval=function(cb,ms){var a=[].slice.call(arguments,2);return si(function(){if(!paused)cb.apply(null,a)},ms)};
window.setTimeout=function(cb,ms){var a=[].slice.call(arguments,2);function go(){if(paused)st(go,50);else if(typeof cb==="function")cb.apply(null,a)}return st(go,ms)};
function toggle(){paused=!paused;if(paused)since=clock();else{shift+=clock()-since;var q=held;held=[];q.forEach(function(cb){raf(function(t){cb(t-shift)})})}
 btn.textContent=paused?"\u25B6 Reprendre":"\u23F8 Pause";btn.setAttribute("aria-pressed",String(paused))}
var btn=document.createElement("button");btn.type="button";btn.textContent="\u23F8 Pause";btn.title="Pause (touche P)";
btn.setAttribute("style","position:fixed;top:6px;right:8px;z-index:2147483647;font:600 12px system-ui,sans-serif;"+
 "padding:4px 10px;border-radius:6px;border:1px solid rgba(242,165,65,.7);background:rgba(20,24,30,.82);color:#f2a541;cursor:pointer");
btn.addEventListener("click",toggle);
addEventListener("keydown",function(e){var n=e.target&&e.target.tagName;if((e.key==="p"||e.key==="P")&&n!=="INPUT"&&n!=="TEXTAREA"&&n!=="SELECT"){toggle();e.preventDefault()}});
var last=0;function size(){var h=Math.ceil(document.documentElement.scrollHeight);if(Math.abs(h-last)>4){last=h;parent.postMessage({aetherSim:"taille",h:h},"*")}}
function ready(){document.body.appendChild(btn);size();try{new ResizeObserver(size).observe(document.body)}catch(e){}si(size,1000)}
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",ready);else ready();
})();
