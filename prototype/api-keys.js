(() => {
  const main = document.querySelector("main");
  const panel = document.createElement("section");
  panel.id = "api-keys";
  panel.hidden = true;
  main.append(panel);

  const styles = document.createElement("style");
  styles.textContent = `
    .api-open #screen,.api-open #partner-link,.api-open .journal-link,.api-open #intake-journal,.api-open #web-upload,.api-open #glass-root,.api-open main nav{display:none!important}
    #api-keys{padding:24px 0 80px;max-width:920px;min-width:0}
    #api-keys a{color:var(--accent)}
    #api-keys article,#api-keys .key-create,#api-keys .key-secret{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px;margin:16px 0}
    #api-keys p{line-height:1.5;overflow-wrap:anywhere}
    #api-keys input{display:block;width:100%;font:inherit;color:var(--text);background:var(--page);border:1px solid var(--line);border-radius:8px;padding:11px;margin:12px 0}
    #api-keys button{font:inherit;border:1px solid var(--line);border-radius:8px;padding:9px 13px;background:var(--surface);color:var(--text);margin:4px 8px 4px 0;cursor:pointer}
    #api-keys button.primary{background:var(--teal);color:var(--white)}
    #api-keys button:disabled{opacity:.5;cursor:wait}
    #api-keys small{display:block;margin:8px 0}
    #api-keys [hidden]{display:none!important}
    @media(min-width:860px){main:has(.workspace-sidebar)>#api-keys{grid-column:2;grid-row:2}}
  `;
  document.head.append(styles);

  function node(tag, text) {
    const element = document.createElement(tag);
    element.textContent = text;
    return element;
  }
  function makeLink() {
    const link = node("a", "API для агента");
    link.href = "#api";
    return link;
  }
  const shortcut = makeLink();
  shortcut.className = "journal-link";
  const existing = main.querySelector(".journal-link");
  if (existing) existing.after(shortcut);
  else main.append(shortcut);
  const sidebar = document.querySelector(".workspace-documents");
  const sidebarLink = sidebar ? makeLink() : null;
  if (sidebarLink) sidebar.append(sidebarLink);

  let version = 0;
  let keys = [];
  const dateLabel = value => {
    if (!value) return "—";
    const date = new Date(typeof value === "number" ? value * 1000 : value);
    return Number.isFinite(+date) ? date.toLocaleString("ru-RU") : "—";
  };
  async function post(path, data = {}) {
    const initData = window.Telegram?.WebApp?.initData;
    const response = await fetch(path, {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({...data, ...(initData ? {initData} : {})}),
    });
    if (!response.ok) {
      const error = new Error(response.status === 401 || response.status === 403
        ? "Войдите в кабинет через персональную ссылку из бота."
        : "Не удалось выполнить запрос. Повторите позже.");
      error.status = response.status;
      throw error;
    }
    return response.json();
  }
  function render() {
    panel.replaceChildren();
    const back = node("a", "← К сводке"); back.href = "#";
    panel.append(back, node("h1", "API для агента"), node("p", "Создайте ключ, чтобы агент загружал документы от вашего имени и проверял их обработку."));
    const docs = node("a", "Документация и примеры запросов");
    docs.href = "/api-docs.html"; docs.target = "_blank"; docs.rel = "noopener";
    panel.append(docs);
    const notice = node("p", ""); notice.setAttribute("role", "status"); panel.append(notice);
    const form = node("form", ""); form.className = "key-create";
    const label = node("label", "Название подключения");
    const input = node("input", ""); input.placeholder = "Например, агент склада"; input.maxLength = 80; input.required = true;
    label.append(input);
    const create = node("button", "Создать API-ключ"); create.type = "submit"; create.className = "primary";
    form.append(label, create); panel.append(form);
    form.onsubmit = async event => {
      event.preventDefault(); if (!input.value.trim()) return;
      create.disabled = true; notice.textContent = "";
      try {
        const result = await post("/api/keys/create", {name: input.value.trim()});
        const token = result.key || result.token || result.api_key;
        if (typeof token !== "string" || !token) throw new Error("Ключ создан, но ответ не удалось прочитать. Отзовите его и создайте новый.");
        const secret = node("section", ""); secret.className = "key-secret";
        secret.append(node("strong", "Сохраните API-ключ"), node("p", "Полный ключ показывается один раз. Передайте его агенту через защищённое хранилище."));
        const value = node("input", ""); value.type = "password"; value.readOnly = true; value.value = token; value.setAttribute("aria-label", "Новый API-ключ"); value.autocomplete = "off";
        const copy = node("button", "Скопировать ключ"); copy.type = "button";
        copy.onclick = async () => {
          try { await navigator.clipboard.writeText(value.value); copy.textContent = "Скопирован"; }
          catch { value.type = "text"; value.focus(); value.select(); copy.textContent = "Выделен для копирования"; }
        };
        const reveal = node("button", "Показать ключ"); reveal.type = "button";
        reveal.onclick = () => { value.type = value.type === "password" ? "text" : "password"; reveal.textContent = value.type === "password" ? "Показать ключ" : "Скрыть символы"; };
        const hide = node("button", "Я сохранил ключ"); hide.type = "button";
        hide.onclick = () => { value.value = ""; secret.remove(); };
        secret.append(value, copy, reveal, hide); form.after(secret); input.value = "";
        const list = await post("/api/keys/list"); keys = list.keys || [];
        renderList();
      } catch (error) { notice.textContent = error.message; }
      finally { create.disabled = false; }
    };
    const listing = node("div", ""); listing.className = "key-list"; panel.append(listing);
    function renderList() {
      listing.replaceChildren(node("h2", "Мои подключения"));
      if (!keys.length) listing.append(node("p", "Ключей пока нет."));
      for (const key of keys) {
        const card = node("article", "");
        card.append(node("strong", key.name || "Подключение"));
        if (key.prefix) card.append(node("small", "Ключ · " + key.prefix + "…"));
        card.append(node("small", "Создан · " + dateLabel(key.created_at)));
        card.append(node("small", "Последнее использование · " + dateLabel(key.last_used_at || key.last_used)));
        if (key.expires_at) card.append(node("small", "Действует до · " + dateLabel(key.expires_at)));
        if (key.revoked_at || key.revoked) { card.append(node("p", "Отозван")); listing.append(card); continue; }
        const revoke = node("button", "Отозвать ключ"); revoke.type = "button";
        revoke.onclick = () => {
          revoke.hidden = true;
          const confirmation = node("div", ""); confirmation.append(node("p", "Подтвердите отзыв. Агент с этим ключом потеряет доступ."));
          const yes = node("button", "Подтвердить отзыв"), no = node("button", "Отмена"); yes.type = no.type = "button";
          no.onclick = () => { confirmation.remove(); revoke.hidden = false; };
          yes.onclick = async () => {
            yes.disabled = true;
            try { await post("/api/keys/revoke", {id: key.id}); const result = await post("/api/keys/list"); keys = result.keys || []; renderList(); }
            catch (error) { notice.textContent = error.message; yes.disabled = false; }
          };
          confirmation.append(yes, no); card.append(confirmation);
        };
        card.append(revoke); listing.append(card);
      }
    }
    renderList();
  }
  async function route() {
    const active = location.hash === "#api";
    document.body.classList.toggle("api-open", active); panel.hidden = !active;
    if (sidebarLink) sidebarLink.setAttribute("aria-current", active ? "page" : "false");
    const request = ++version;
    // Replacing the subtree clears any one-time key from the previous view.
    panel.replaceChildren();
    if (!active) return;
    panel.append(node("h1", "API для агента"), node("p", "Загружаем подключения…"));
    try {
      const result = await post("/api/keys/list"); if (request !== version) return;
      keys = result.keys || []; render();
    } catch (error) {
      if (request !== version) return;
      panel.replaceChildren(node("h1", "API для агента"), node("p", error.message));
      const login = node("a", "Войти через бота"); login.href = "https://t.me/tovarkonttolbot"; panel.append(login);
    }
  }
  window.addEventListener("hashchange", route);
  window.addEventListener("session-ended", route);
  window.addEventListener("load", route);
  route();
})();
