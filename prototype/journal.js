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
      if(data.entries.length){
        const filter=node("select","");filter.setAttribute("aria-label","История загрузок по пользователю");
        const all=node("option","Все отправители · последние 100 записей");all.value="";filter.append(all);
        for(const [id,label] of new Map(data.entries.map(e=>[e.user_id,e.alias||e.display_name||String(e.user_id)]))){
          const option=node("option",label+" · ID "+id);option.value=String(id);filter.append(option);
        }
        filter.onchange=()=>{for(const card of journal.querySelectorAll("article[data-user]"))card.hidden=!!filter.value&&card.dataset.user!==filter.value};
        journal.append(filter);
      }
      for(const entry of data.entries){
        const card=node("article","");card.dataset.user=String(entry.user_id);
        card.append(node("strong",entry.filename||"Текстовое сообщение"));
        card.append(node("p",(labels[entry.role]||entry.role)+" · "+(entry.alias||entry.display_name)));
        card.append(node("small","Telegram ID · "+entry.user_id));
        if(entry.alias&&entry.display_name)card.append(node("p","Имя при загрузке · "+entry.display_name));
        const date=new Date(entry.received_at);
        card.append(node("small",date.toLocaleString("ru-RU")+" · Получено"));
        if(entry.origin)card.append(node("p","Источник · "+entry.origin));
        if(entry.text)card.append(node("p",entry.text));
        if(data.scope==="all"){
          const edit=node("button","Назначить имя");edit.type="button";
          edit.onclick=()=>{
            edit.hidden=true;
            const form=node("form",""),input=node("input","");
            input.placeholder="Имя или название компании";input.maxLength=120;input.value=entry.alias||entry.display_name||"";input.setAttribute("aria-label","Имя отправителя");
            const save=node("button","Сохранить"),cancel=node("button","Отмена");save.type="submit";cancel.type="button";
            form.append(input,save,cancel);card.append(form);input.focus();
            cancel.onclick=()=>{form.remove();edit.hidden=false};
            form.onsubmit=async event=>{
              event.preventDefault();save.disabled=true;
              try{
                const response=await fetch("/api/people",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json"},body:JSON.stringify({user_id:entry.user_id,name:input.value, ...(initData?{initData}:{})})});
                if(!response.ok)throw Error();await show();
              }catch{save.disabled=false;save.textContent="Повторить сохранение"}
            };
          };card.append(edit);
        }
        journal.append(card);
      }
    }catch{if(request===version)info.textContent="Не удалось открыть журнал. Переоткройте приложение через бота и повторите."}
  }
  window.addEventListener("session-ended",()=>{journal.replaceChildren();show()});window.addEventListener("hashchange",show);window.addEventListener("load",show);show();
})();
