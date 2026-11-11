(()=>{
  const view=document.createElement("section");view.id="web-upload";view.hidden=true;
  view.innerHTML='<a href="#journal">← Журнал загрузок</a><h1>Загрузить документ</h1><p>Excel или CSV до 100 МБ. Документ появится в журнале с вашим именем.</p><form><label class="upload-zone">Выберите файл<input type="file" accept=".xlsx,.csv" required></label><p class="upload-filename"></p><button type="submit">Загрузить</button><button type="button" class="cancel-upload" hidden>Отменить</button><progress max="100" value="0" hidden></progress><p role="status"></p></form><a href="https://t.me/tovarkonttolbot">Получить ссылку для входа в боте</a>';
  document.querySelector("main").append(view);
  const link=document.createElement("a");link.href="#upload";link.textContent="Загрузить большой файл →";link.className="journal-link";document.querySelector(".journal-link").after(link);
  const form=view.querySelector("form"),input=view.querySelector("input"),progress=view.querySelector("progress"),status=view.querySelector('[role="status"]'),submit=view.querySelector('[type="submit"]'),cancel=view.querySelector(".cancel-upload");
  let pending=null;
  input.addEventListener("change",()=>{view.querySelector(".upload-filename").textContent=input.files[0]?.name||"";status.textContent=""});
  form.onsubmit=event=>{
    event.preventDefault();if(pending)return;
    const file=input.files[0];if(!file)return;
    if(!/\.(xlsx|csv)$/i.test(file.name)||file.size>100*1024*1024||!file.size){status.textContent="Выберите XLSX или CSV размером от 1 байта до 100 МБ.";return}
    const xhr=new XMLHttpRequest();pending=xhr;submit.disabled=true;cancel.hidden=false;progress.hidden=false;progress.value=0;
    xhr.open("POST","/api/upload");xhr.setRequestHeader("Content-Type","application/octet-stream");xhr.setRequestHeader("X-File-Name",encodeURIComponent(file.name));
    xhr.upload.onprogress=e=>{if(e.lengthComputable)progress.value=e.loaded/e.total*100;status.textContent=progress.value===100?"Сохраняем документ…":"Загружаем · "+Math.round(progress.value)+"%"};
    const finish=message=>{pending=null;submit.disabled=false;cancel.hidden=true;status.textContent=message};
    xhr.onload=()=>{
      if(xhr.status===200||xhr.status===201){let result;try{result=JSON.parse(xhr.responseText)}catch{finish("Не удалось проверить сохранение. Посмотрите журнал перед повтором.");return}
        finish("Документ сохранён. Запись №"+result.id+". Ожидает проверки.");input.value="";view.querySelector(".upload-filename").textContent="";return}
      finish(xhr.status===401?"Войдите по персональной ссылке из бота.":xhr.status===400?"Выберите в боте роль поставщика или сотрудника, затем повторите загрузку.":xhr.status===413?"Файл превышает лимит 100 МБ.":"Не удалось загрузить файл. Проверьте журнал перед повторной отправкой.");
    };
    xhr.onerror=()=>finish("Соединение прервано. Проверьте журнал перед повторной отправкой.");
    xhr.onabort=()=>finish("Загрузка отменена.");
    xhr.send(file);
  };
  cancel.onclick=()=>pending?.abort();
  window.addEventListener("beforeunload",event=>{if(pending){event.preventDefault();event.returnValue=""}});
  function route(){const open=location.hash==="#upload";view.hidden=!open;document.body.classList.toggle("upload-open",open)}
  window.addEventListener("hashchange",route);route();
})();
