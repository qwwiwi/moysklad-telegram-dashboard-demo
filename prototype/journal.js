(()=>{
  const journal=document.createElement("section");
  journal.id="intake-journal";
  journal.hidden=true;
  document.querySelector("main").append(journal);
  const link=document.createElement("a");
  link.href="#journal";link.className="journal-link";link.textContent="Журнал загрузок →";
  document.getElementById("partner-link").after(link);
  const labels={supplier:"Поставщик",employee:"Сотрудник",file:"Файл",text:"Сообщение"};
  function node(tag,text){const el=document.createElement(tag);el.textContent=text;return el}
  let version=0;
  async function show(){
    const active=location.hash==="#journal";
    document.body.classList.toggle("journal-open",active);journal.hidden=!active;
    const request=++version;if(!active)return;
    journal.replaceChildren(node("h1","Журнал загрузок"));
    const back=node("a","← К сводке");back.href="#";journal.prepend(back);
    const initData=window.Telegram?.WebApp?.initData;
    const info=node("p","Загружаем записи…");journal.append(info);
    try{
      const response=await fetch("/api/journal",{method:"POST",headers:{"Content-Type":"application/json"},credentials:"same-origin",cache:"no-store",body:JSON.stringify(initData?{initData}:{})});
      if(request!==version)return;
      if(response.status===401||response.status===403){
        info.textContent="Для просмотра журнала войдите через Telegram.";
        const login=node("a","Вход по ссылке");login.href="#login";journal.append(login);return;
      }
      if(!response.ok)throw Error();
      const data=await response.json();if(request!==version)return;
      info.textContent=data.entries.length?"Поступившие документы ожидают проверки.":"Загрузок пока нет. Отправьте Excel или сообщение боту.";
      for(const entry of data.entries){
        const card=node("article","");
        card.append(node("strong",entry.filename||"Текстовое сообщение"));
        card.append(node("p",(labels[entry.role]||entry.role)+" · "+entry.display_name));
        const date=new Date(entry.received_at);
        card.append(node("small",date.toLocaleString("ru-RU")+" · Получено"));
        if(entry.origin)card.append(node("p","Источник · "+entry.origin));
        if(entry.text)card.append(node("p",entry.text));
        journal.append(card);
      }
    }catch{if(request===version)info.textContent="Не удалось открыть журнал. Переоткройте приложение через бота и повторите."}
  }
  window.addEventListener("session-ended",()=>{journal.replaceChildren();show()});window.addEventListener("hashchange",show);window.addEventListener("load",show);show();
})();
