const observer=new IntersectionObserver(entries=>{for(const e of entries){if(e.isIntersecting)e.target.classList.add('visible')}},{threshold:.12});
document.querySelectorAll('.reveal').forEach(el=>observer.observe(el));
const nav=document.querySelector('.nav');addEventListener('scroll',()=>nav.style.boxShadow=scrollY>20?'0 14px 50px #0008':'none');
