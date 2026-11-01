(function(){
  var d=document,root=d.documentElement,orig=root.getAttribute('data-persona');
  var reduce=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function push(o){window.dataLayer=window.dataLayer||[];window.dataLayer.push(o);}
  function $$(q,el){return Array.prototype.slice.call((el||d).querySelectorAll(q));}
  // Persona switch: real links; with JS the thumb slides and the palette crossfades before navigating.
  $$('.switch a[data-to]').forEach(function(a){a.addEventListener('click',function(e){
    var to=a.getAttribute('data-to');
    if(e.defaultPrevented||e.button!==0||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;
    push({event:'persona_switch',persona:to});
    if(to===orig||reduce)return;
    e.preventDefault();
    root.classList.add('switching');root.setAttribute('data-persona',to);
    setTimeout(function(){window.location.href=a.href;},260);
  });});
  window.addEventListener('pageshow',function(e){if(e.persisted){root.setAttribute('data-persona',orig);root.classList.remove('switching');}});
  // Analytics: mailto/tel and outbound clicks (delegated).
  d.addEventListener('click',function(e){
    var a=e.target.closest&&e.target.closest('a[href]');if(!a)return;
    var h=a.getAttribute('href');
    if(/^mailto:/i.test(h))push({event:'contact_click',method:'email'});
    else if(/^tel:/i.test(h))push({event:'contact_click',method:'phone'});
    else if(/^https?:/i.test(a.href)&&a.hostname!==location.hostname&&!a.classList.contains('vplay'))push({event:'outbound_click',url:a.href});
  },true);
  // Contact form: record the lead, then let the normal POST go through.
  var form=d.getElementById('contact-form'),sel=d.getElementById('f-topic');
  if(form&&sel){
    var want=(location.search.match(/[?&]topic=([\w-]+)/)||[])[1];
    if(want)$$('option[data-key]',sel).forEach(function(o){if(o.getAttribute('data-key')===want)sel.value=o.value;});
    form.addEventListener('submit',function(){push({event:'generate_lead',form:'contact',topic:sel.value});});
  }
  // Wedding date check: opens the availability form in a new tab (the date itself is not sent).
  $$('form.datecheck').forEach(function(f){f.addEventListener('submit',function(){
    var v=f.querySelector('input[type=date]').value,n=f.querySelector('.dc-note');
    push({event:'check_date'});
    if(n)n.textContent='Opening the availability form in a new tab'+(v?'. Choose '+new Date(v+'T12:00').toLocaleDateString('en-US',{month:'long',day:'numeric',year:'numeric'})+' there.':'.');
  });});
  // Stats count up when scrolled into view (final values are already in the HTML).
  // A number already on screen at load keeps its value: data never rewinds in view. Only offscreen ones start at 0.
  var nums=$$('[data-count]').filter(function(n){return n.getBoundingClientRect().top>window.innerHeight;});
  if(nums.length&&'IntersectionObserver' in window&&!reduce){
    var fmtOf=function(el){var dec=+(el.getAttribute('data-dec')||0),suf=el.getAttribute('data-suffix')||'';
      return function(v){return Number(v.toFixed(dec)).toLocaleString('en-US',{minimumFractionDigits:dec,maximumFractionDigits:dec})+suf;};};
    nums.forEach(function(el){el.textContent=fmtOf(el)(0);});
    var io=new IntersectionObserver(function(es){es.forEach(function(en){
      if(!en.isIntersecting)return;io.unobserve(en.target);
      var el=en.target,end=parseFloat(el.getAttribute('data-count')),fmt=fmtOf(el),t0=null;
      function step(t){if(t0===null)t0=t;var k=Math.min(1,(t-t0)/1300);el.textContent=fmt(end*(1-Math.pow(1-k,3)));if(k<1)requestAnimationFrame(step);}
      requestAnimationFrame(step);
    });},{threshold:.5});
    nums.forEach(function(n){io.observe(n);});
  }
  // Scroll-in: card grids below the fold arrive once, 80ms apart in reading order. Above-the-fold content is never hidden.
  if('IntersectionObserver' in window&&!reduce){
    var groups=$$('.caps,.grid4,.grid3,.work,.adv,.lcards,.vgrid,.auth-list').filter(function(g){return g.getBoundingClientRect().top>window.innerHeight;});
    var gio=new IntersectionObserver(function(es){es.forEach(function(en){
      if(!en.isIntersecting)return;gio.unobserve(en.target);
      Array.prototype.slice.call(en.target.children).forEach(function(c,i){c.style.setProperty('--rv-d',Math.min(i,6)*80+'ms');c.classList.add('in');
        setTimeout(function(){c.classList.remove('rv','in');c.style.removeProperty('--rv-d');},1400+Math.min(i,6)*80);});
    });},{rootMargin:'0px 0px -12% 0px'});
    groups.forEach(function(g){Array.prototype.slice.call(g.children).forEach(function(c){c.classList.add('rv');});gio.observe(g);});
  }
  // Phone nav is one swipeable row: keep the current page's link in view.
  var cur=d.querySelector('.pnav a[aria-current]'),pn=d.querySelector('.pnav');
  if(cur&&pn&&pn.scrollWidth>pn.clientWidth){var l=cur.offsetLeft-pn.offsetLeft;pn.scrollLeft=Math.max(0,l-(pn.clientWidth-cur.offsetWidth)/2);}
  // Miles tracker: tap a marker to toggle its caption.
  $$('.miles .pin').forEach(function(p){p.addEventListener('click',function(){
    var on=p.getAttribute('aria-expanded')==='true';
    $$('.miles .pin').forEach(function(q){q.setAttribute('aria-expanded','false');});
    p.setAttribute('aria-expanded',on?'false':'true');
  });});
  // Lite YouTube: the link plays in place as a youtube-nocookie iframe (created only on click).
  d.addEventListener('click',function(e){
    var a=e.target.closest&&e.target.closest('a.vplay');
    if(!a||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey||e.button!==0)return;
    e.preventDefault();
    var id=a.getAttribute('data-yt'),list=a.getAttribute('data-list'),t=a.getAttribute('data-title')||'Video',f=d.createElement('iframe');
    f.src='https://www.youtube-nocookie.com/embed/'+(list?'videoseries?list='+list+'&':id+'?')+'autoplay=1&rel=0';
    f.title=t;f.setAttribute('allow','autoplay; encrypted-media; picture-in-picture; fullscreen');f.setAttribute('allowfullscreen','');
    var box=d.createElement('div');box.className='vframe';box.appendChild(f);a.parentNode.replaceChild(box,a);f.focus();
    push({event:'video_play',video_id:id||list,video_title:t});
  });
  // Lightbox: <a class="lb" data-lb="group"> opens in a <dialog>; arrows navigate, Esc closes.
  var dlg,img,cap,grp=[],idx=0,opener;
  function show(i){idx=(i+grp.length)%grp.length;var a=grp[idx],im=a.querySelector('img');img.src=a.href;img.alt=im?im.alt:'';cap.textContent=im?im.alt:'';
    dlg.querySelector('.lb-p').hidden=dlg.querySelector('.lb-n').hidden=grp.length<2;}
  function build(){dlg=d.createElement('dialog');dlg.className='lightbox';dlg.setAttribute('aria-label','Photo viewer');
    dlg.innerHTML='<figure><img alt=""><figcaption></figcaption></figure><button type="button" class="lb-p" aria-label="Previous photo">&#8249;</button><button type="button" class="lb-n" aria-label="Next photo">&#8250;</button><button type="button" class="lb-x" aria-label="Close">&#215;</button>';
    d.body.appendChild(dlg);img=dlg.querySelector('img');cap=dlg.querySelector('figcaption');
    dlg.querySelector('.lb-p').onclick=function(){show(idx-1);};dlg.querySelector('.lb-n').onclick=function(){show(idx+1);};
    dlg.querySelector('.lb-x').onclick=function(){dlg.close();};
    dlg.addEventListener('click',function(e){if(e.target===dlg)dlg.close();});
    dlg.addEventListener('keydown',function(e){if(e.key==='ArrowLeft'){e.preventDefault();show(idx-1);}else if(e.key==='ArrowRight'){e.preventDefault();show(idx+1);}});
    dlg.addEventListener('close',function(){img.removeAttribute('src');if(opener)opener.focus();});}
  d.addEventListener('click',function(e){
    var a=e.target.closest&&e.target.closest('a.lb');
    if(!a||e.metaKey||e.ctrlKey||e.shiftKey||e.button!==0||typeof HTMLDialogElement!=='function')return;
    e.preventDefault();if(!dlg)build();opener=a;grp=$$('a.lb[data-lb="'+a.getAttribute('data-lb')+'"]');show(grp.indexOf(a));dlg.showModal();dlg.querySelector('.lb-x').focus();
  });
  // Article category chips: real links to /articles/category/<slug>/; on the index they also filter in place.
  var chips=d.querySelector('.chips[data-filter]');
  if(chips)chips.addEventListener('click',function(e){
    var a=e.target.closest&&e.target.closest('a');
    if(!a||e.metaKey||e.ctrlKey||e.shiftKey||e.button!==0)return;
    e.preventDefault();var c=a.getAttribute('data-cat');
    chips.querySelectorAll('a').forEach(function(x){if(x===a)x.setAttribute('aria-current','true');else x.removeAttribute('aria-current');});
    d.querySelectorAll('#articles-list .art').forEach(function(x){x.hidden=!!c&&x.getAttribute('data-cat')!==c;});
  });
  // Reading progress (articles) and back-to-top.
  var bar=d.querySelector('.progress span'),art=d.querySelector('.prose'),top=d.querySelector('.totop'),tick=false;
  function onScroll(){tick=false;var y=window.scrollY||0;
    if(bar&&art){var r=art.getBoundingClientRect(),h=r.height-window.innerHeight*0.6,p=h>0?Math.min(1,Math.max(0,-r.top/h)):1;bar.style.transform='scaleX('+p+')';}
    if(top)top.classList.toggle('on',y>900);}
  window.addEventListener('scroll',function(){if(!tick){tick=true;requestAnimationFrame(onScroll);}},{passive:true});onScroll();
  if(top)top.addEventListener('click',function(e){e.preventDefault();window.scrollTo({top:0,behavior:reduce?'auto':'smooth'});var f=d.querySelector('.switch a');if(f)f.focus({preventScroll:true});});
})();
