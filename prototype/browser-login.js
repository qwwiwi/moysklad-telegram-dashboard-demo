(() => {
  let token = "";
  function takeLink() {
    if (!location.hash.startsWith("#login=")) return;
    token = location.hash.slice(7);
    history.replaceState(history.state, "", location.pathname + location.search + "#login");
  }
  takeLink();

  function attach() {
    const dialog = document.createElement("dialog");
    dialog.className = "browser-signin";
    dialog.setAttribute("aria-labelledby", "signin-title");
    dialog.innerHTML = '<h2 id="signin-title">Вход в ТОВАРНО</h2><p role="status"></p><div class="signin-actions"><button type="button">Войти в кабинет</button><a href="https://t.me/tovarkonttolbot">Получить ссылку в боте</a><button type="button">Закрыть</button></div>';
    const styles = document.createElement("style");
    styles.textContent = `
      dialog.browser-signin{box-sizing:border-box;position:fixed;inset:0;margin:auto;width:min(400px,calc(100% - 32px));height:fit-content;padding:24px;border:1px solid var(--line);border-radius:18px;background:var(--surface);color:var(--text);box-shadow:0 12px 56px #19263826}
      dialog.browser-signin::backdrop{background:#19263870}
      .browser-signin h2{margin:0;font-size:23px}.browser-signin p{margin:12px 0 20px}
      .signin-actions{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
      .signin-actions button,.signin-actions a,.session-signout{border:1px solid var(--line);border-radius:9px;background:var(--surface);color:var(--text);font:inherit;padding:9px 14px;cursor:pointer}
      .signin-actions button:first-child,.signin-actions a{background:#192638;color:#f5f9fa}
      .signin-actions [hidden],.session-signout[hidden]{display:none!important}
      .session-signout{margin:12px 0}
    `;
    document.head.append(styles);
    document.body.append(dialog);
    const [confirm, close] = dialog.querySelectorAll("button");
    const message = dialog.querySelector("p");
    const bot = dialog.querySelector("a");
    const signout = document.createElement("button");
    signout.type = "button";
    signout.textContent = "Выйти из кабинета";
    signout.className = "session-signout";
    signout.hidden = true;
    document.querySelector("main").append(signout);
    const post = (path, data={}) => fetch(path, {
      method:"POST", credentials:"same-origin", cache:"no-store",
      headers:{"Content-Type":"application/json"}, body:JSON.stringify(data),
    });
    async function session() {
      try {
        const response = await post("/api/session");
        signout.hidden = !response.ok || !(await response.json()).authenticated;
      } catch {signout.hidden = true}
    }
    function route() {
      takeLink();
      if (location.hash !== "#login") {
        token = "";
        if (dialog.open) dialog.close();
        return;
      }
      confirm.hidden = !token;
      bot.hidden = !!token;
      message.textContent = token
        ? "Откройте личный кабинет в этом браузере с правами вашего аккаунта Telegram."
        : "Нажмите «Вход по ссылке» в боте и откройте полученную ссылку в этом браузере.";
      if (!dialog.open) dialog.showModal();
    }
    confirm.onclick = async () => {
      if (!token || confirm.disabled) return;
      confirm.disabled = true;
      try {
        const response = await post("/api/login", {token});
        if (response.ok) {
          token = "";
          signout.hidden = false;
          dialog.close();
          location.replace(new URL(location.href).searchParams.get("next")==="upload"?"#upload":"#journal");
        } else if ([400,401,403,410].includes(response.status)) {
          token = "";
          confirm.hidden = true;
          bot.hidden = false;
          message.textContent = "Срок действия ссылки истёк или она уже использована. Получите новую ссылку в боте.";
        } else throw Error();
      } catch {
        message.textContent = "Сервис временно недоступен. Повторите вход.";
      } finally {confirm.disabled = false}
    };
    close.onclick = () => location.replace("#");
    dialog.addEventListener("cancel", event => {event.preventDefault();location.replace("#")});
    signout.onclick = async () => {
      signout.disabled = true;
      try {
        if (!(await post("/api/logout")).ok) throw Error();
        signout.hidden = true;
        location.replace("#");
        window.dispatchEvent(new Event("session-ended"));
      } catch { signout.textContent = "Повторить выход из кабинета" }
      finally {signout.disabled = false}
    };
    window.addEventListener("hashchange", route);
    window.addEventListener("pageshow", session);
    route();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded",attach,{once:true});
  else attach();
})();
