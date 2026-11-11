(()=>{
 const screen=document.getElementById("screen");let scheduled=false;
 async function update(){
   scheduled=false;
   if(!["Сводка","Финансы"].includes(screen.querySelector("h1")?.textContent)||screen.querySelector(".direct-finance"))return;
   const panel=document.createElement("section");panel.className="direct-finance panel";panel.hidden=true;screen.append(panel);
   try{
     const initData=window.Telegram?.WebApp?.initData;
     const response=await fetch("/api/import/status",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify(initData?{initData}:{})});
     if(!response.ok)return;
     const data=await response.json();const docs=new Map();
     for(const item of data.imports.filter(i=>i.status==="posted")){
       for(const row of item.rows||[])docs.set([row.date,row.platform,row.order,row.code||row.article||row.name].join("|"),row);
     }
     if(!docs.size)return;
     let cost=0,sales=0,quantity=0;
     for(const row of docs.values()){quantity+=Number(row.quantity);cost+=Number(row.purchase_minor)*Number(row.quantity)/100;sales+=Number(row.sale_minor)*Number(row.quantity)/100}
     panel.hidden=false;
     const title=document.createElement("h2");title.textContent="Прямые отгрузки поставщиков";panel.append(title);
     for(const [label,value] of [["Отгружено",quantity+" шт."],["Продажи",sales],["Долг поставщикам",cost],["Дебиторская задолженность",sales],["Валовая прибыль",sales-cost]]){
       const p=document.createElement("p");p.textContent=label+" · "+(typeof value==="number"?value.toLocaleString("ru-RU")+" ₽":value);panel.append(p)
     }
     const note=document.createElement("small");note.textContent="По проведённым импортам. Оплаты учитываются отдельно. Валовая прибыль до комиссий и налогов.";panel.append(note);
   }catch{}
 }
 new MutationObserver(()=>{if(!scheduled){scheduled=true;requestAnimationFrame(update)}}).observe(screen,{childList:true});
 window.addEventListener("load",update);update();
})();
