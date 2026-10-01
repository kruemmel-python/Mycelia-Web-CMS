(() => {
  "use strict";

  const allowedHttpsOrRelative = (href) => {
    href = String(href || "").trim();
    if (href.startsWith("/") && !href.startsWith("//")) return href;
    try {
      const u = new URL(href);
      return u.protocol === "https:" && !u.username && !u.password ? href : null;
    } catch (_) { return null; }
  };

  const wrapRun = (run) => {
    let node = document.createTextNode(run.text || "");
    const marks = Array.isArray(run.marks) ? run.marks : [];
    const wrappers = [["bold","strong"],["italic","em"],["underline","u"],["strike","s"],["code","code"]];
    wrappers.forEach(([mark, tag]) => {
      if (marks.includes(mark)) { const el = document.createElement(tag); el.appendChild(node); node = el; }
    });
    if (run.size === "small" || run.size === "large") { const sp=document.createElement("span"); sp.dataset.rtSize=run.size; sp.appendChild(node); node=sp; }
    if (["accent","muted","warning"].includes(run.tone)) { const sp=document.createElement("span"); sp.dataset.rtTone=run.tone; sp.appendChild(node); node=sp; }
    if (run.link) { const a = document.createElement("a"); a.href = run.link; a.appendChild(node); node = a; }
    return node;
  };

  const appendRuns = (parent, runs) => (runs || []).forEach((r) => parent.appendChild(wrapRun(r)));

  const docToDom = (doc, canvas) => {
    canvas.replaceChildren();
    (doc.blocks || []).forEach((b) => {
      let el;
      if (b.type === "paragraph") { el = document.createElement("p"); appendRuns(el,b.runs); if (["center","right"].includes(b.align)) el.dataset.rtAlign=b.align; }
      else if (b.type === "heading") { el = document.createElement(b.level === 3 ? "h3" : "h2"); appendRuns(el,b.runs); if (["center","right"].includes(b.align)) el.dataset.rtAlign=b.align; }
      else if (b.type === "quote") { el = document.createElement("blockquote"); appendRuns(el,b.runs); }
      else if (b.type === "bullet_list" || b.type === "ordered_list") {
        el = document.createElement(b.type === "bullet_list" ? "ul" : "ol");
        (b.items || []).forEach((item) => { const li=document.createElement("li"); appendRuns(li,item); el.appendChild(li); });
      } else if (b.type === "code") {
        el = document.createElement("pre"); el.dataset.language = b.language || "text"; el.textContent = b.text || "";
      } else if (b.type === "divider") el = document.createElement("hr");
      else if (b.type === "button_link") {
        el=document.createElement("p"); const a=document.createElement("a"); a.dataset.rtButton="1"; a.href=b.href; a.textContent=b.text; el.appendChild(a);
      } else if (b.type === "table") {
        el=document.createElement("table"); const tbody=document.createElement("tbody");
        (b.rows||[]).forEach((row)=>{ const tr=document.createElement("tr"); row.forEach((cell)=>{const td=document.createElement("td"); appendRuns(td,cell); tr.appendChild(td);}); tbody.appendChild(tr); }); el.appendChild(tbody);
      }
      if (el) canvas.appendChild(el);
    });
    if (!canvas.childNodes.length) canvas.appendChild(document.createElement("p"));
  };

  const inlineRuns = (root) => {
    const out=[];
    const walk=(node, marks=[], link=null) => {
      if (node.nodeType === Node.TEXT_NODE) {
        if (node.nodeValue) { const pe=node.parentElement; const toneEl=pe&&pe.closest?pe.closest("[data-rt-tone]"):null; const sizeEl=pe&&pe.closest?pe.closest("[data-rt-size]"):null; out.push({text:node.nodeValue,marks:[...new Set(marks)],...(link?{link}:{}),...(toneEl?{tone:toneEl.dataset.rtTone}:{}),...(sizeEl?{size:sizeEl.dataset.rtSize}:{})}); }
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const tag=node.tagName.toLowerCase();
      let next=[...marks], nextLink=link, nextTone=null, nextSize=null;
      const inheritedTone = node.parentElement && node.parentElement.closest ? node.parentElement.closest("[data-rt-tone]") : null;
      const inheritedSize = node.parentElement && node.parentElement.closest ? node.parentElement.closest("[data-rt-size]") : null;
      nextTone = inheritedTone ? inheritedTone.dataset.rtTone : null; nextSize = inheritedSize ? inheritedSize.dataset.rtSize : null;
      if (["b","strong"].includes(tag)) next.push("bold");
      else if (["i","em"].includes(tag)) next.push("italic");
      else if (tag === "u") next.push("underline");
      else if (["s","strike"].includes(tag)) next.push("strike");
      else if (tag === "code") next.push("code");
      else if (tag === "a") nextLink=allowedHttpsOrRelative(node.getAttribute("href"));
      Array.from(node.childNodes).forEach((child)=>walk(child,next,nextLink));
    };
    Array.from(root.childNodes).forEach((n)=>walk(n));
    return out.length ? out : [{text:"",marks:[]}];
  };

  const serialize = (canvas, profile) => {
    const blocks=[];
    const nodes=Array.from(canvas.childNodes);
    const addParagraphFrom=(node)=>blocks.push({type:"paragraph",runs:inlineRuns(node)});
    nodes.forEach((node)=>{
      if (node.nodeType === Node.TEXT_NODE) { if (node.nodeValue.trim()) blocks.push({type:"paragraph",runs:[{text:node.nodeValue,marks:[]}]}); return; }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const tag=node.tagName.toLowerCase();
      if (tag === "p" || tag === "div") {
        const button=node.querySelector(":scope > a[data-rt-button='1']");
        if (button && profile === "document") {
          const href=allowedHttpsOrRelative(button.getAttribute("href"));
          if (href) blocks.push({type:"button_link",text:button.textContent || "",href}); else addParagraphFrom(node);
        } else { const b={type:"paragraph",runs:inlineRuns(node)}; if (["center","right"].includes(node.dataset.rtAlign)) b.align=node.dataset.rtAlign; blocks.push(b); }
      } else if ((tag === "h2" || tag === "h3") && profile !== "compact") {
        blocks.push({type:"heading",level:tag === "h3" ? 3 : 2,runs:inlineRuns(node),...(["center","right"].includes(node.dataset.rtAlign)?{align:node.dataset.rtAlign}:{})});
      } else if (tag === "blockquote") blocks.push({type:"quote",runs:inlineRuns(node)});
      else if (tag === "ul" || tag === "ol") blocks.push({type:tag === "ul" ? "bullet_list" : "ordered_list",items:Array.from(node.children).filter(x=>x.tagName.toLowerCase()==="li").map(inlineRuns)});
      else if (tag === "pre") blocks.push({type:"code",language:node.dataset.language || "text",text:node.textContent || ""});
      else if (tag === "hr" && profile !== "compact") blocks.push({type:"divider"});
      else if (tag === "table" && profile === "document") {
        const rows=Array.from(node.rows).slice(0,100).map((r)=>Array.from(r.cells).slice(0,20).map(inlineRuns));
        if (rows.length && rows[0].length) blocks.push({type:"table",rows});
      } else addParagraphFrom(node);
    });
    if (!blocks.length) blocks.push({type:"paragraph",runs:[{text:"",marks:[]}]});
    return {schema:"MYCELIA_RICHTEXT",version:1,profile,blocks};
  };

  const insertNodeAtSelection=(node)=>{
    const sel=window.getSelection(); if (!sel || !sel.rangeCount) return;
    const range=sel.getRangeAt(0); range.deleteContents(); range.insertNode(node); range.setStartAfter(node); range.collapse(true); sel.removeAllRanges(); sel.addRange(range);
  };

  const initEditor=(host)=>{
    const input=document.getElementById(host.dataset.rtInput); const canvas=host.querySelector(".rt-canvas"); const profile=host.dataset.rtProfile || "document";
    let initial;
    try { initial=JSON.parse(input.value); } catch (_) { initial={schema:"MYCELIA_RICHTEXT",version:1,profile,blocks:[{type:"paragraph",runs:[{text:input.value||"",marks:[]}]}]}; }
    docToDom(initial,canvas);
    const sync=()=>{ input.value=JSON.stringify(serialize(canvas,profile)); };
    canvas.addEventListener("input",sync);
    canvas.addEventListener("paste",(e)=>{ e.preventDefault(); const text=e.clipboardData.getData("text/plain"); document.execCommand("insertText",false,text); sync(); });
    canvas.addEventListener("drop",(e)=>e.preventDefault());
    host.querySelectorAll("[data-rt-cmd]").forEach((b)=>b.addEventListener("click",()=>{canvas.focus(); document.execCommand(b.dataset.rtCmd,false,null); sync();}));
    host.querySelectorAll("[data-rt-block]").forEach((b)=>b.addEventListener("click",()=>{canvas.focus(); document.execCommand("formatBlock",false,b.dataset.rtBlock); sync();}));
    host.querySelectorAll("[data-rt-action]").forEach((b)=>b.addEventListener("click",()=>{
      canvas.focus(); const action=b.dataset.rtAction;
      if (action === "link") { const raw=prompt("HTTPS-Adresse oder interner Pfad (/...):", "https://"); const href=allowedHttpsOrRelative(raw); if (href) document.execCommand("createLink",false,href); }
      else if (action === "inline-code") { const sel=window.getSelection(); if (sel && !sel.isCollapsed && sel.rangeCount) { const code=document.createElement("code"); try { sel.getRangeAt(0).surroundContents(code); } catch (_) {} } }
      else if (action === "divider" && profile !== "compact") insertNodeAtSelection(document.createElement("hr"));
      else if (action === "button-link" && profile === "document") { const label=prompt("Button-Text:","Mehr erfahren"); const href=allowedHttpsOrRelative(prompt("HTTPS-Adresse oder interner Pfad (/...):","/")); if (label && href) { const p=document.createElement("p"),a=document.createElement("a"); a.dataset.rtButton="1"; a.href=href; a.textContent=label.slice(0,200); p.appendChild(a); insertNodeAtSelection(p); } }
      else if (action === "table" && profile === "document") { let rows=Math.min(10,Math.max(1,parseInt(prompt("Zeilen (1-10):","2"),10)||2)); let cols=Math.min(6,Math.max(1,parseInt(prompt("Spalten (1-6):","2"),10)||2)); const t=document.createElement("table"),tb=document.createElement("tbody"); for(let r=0;r<rows;r++){const tr=document.createElement("tr");for(let c=0;c<cols;c++){const td=document.createElement("td");td.textContent="Text";tr.appendChild(td);}tb.appendChild(tr);}t.appendChild(tb);insertNodeAtSelection(t); }
      else if (action.startsWith("tone-") && profile !== "compact") { const sel=window.getSelection(); if(sel&&!sel.isCollapsed&&sel.rangeCount){const sp=document.createElement("span");sp.dataset.rtTone=action.slice(5);try{sel.getRangeAt(0).surroundContents(sp);}catch(_){}} }
      else if (action.startsWith("size-") && profile !== "compact") { const sel=window.getSelection(); if(sel&&!sel.isCollapsed&&sel.rangeCount){const sp=document.createElement("span");sp.dataset.rtSize=action.slice(5);try{sel.getRangeAt(0).surroundContents(sp);}catch(_){}} }
      else if (action.startsWith("align-") && profile !== "compact") { const sel=window.getSelection(); if(sel&&sel.anchorNode){const el=sel.anchorNode.nodeType===Node.ELEMENT_NODE?sel.anchorNode:sel.anchorNode.parentElement;const block=el&&el.closest("p,h2,h3,blockquote");if(block)block.dataset.rtAlign=action.slice(6);} }
      else if (action === "clear") { document.execCommand("removeFormat",false,null); document.execCommand("unlink",false,null); }
      sync();
    }));
    const form=host.closest("form"); if (form) form.addEventListener("submit",sync);
    sync();
  };
  document.addEventListener("DOMContentLoaded",()=>document.querySelectorAll(".rt-editor").forEach(initEditor));
})();
