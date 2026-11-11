(() => {
  const journal = document.getElementById("intake-journal");
  if (!journal) return;

  const style = document.createElement("style");
  style.textContent = `
    .supplier-import{border-top:1px solid var(--line);padding-top:16px;margin-top:16px}
    .supplier-import button{border:1px solid var(--line);background:var(--surface);color:var(--text);border-radius:9px;padding:10px 14px;cursor:pointer;margin:0 8px 8px 0}
    .supplier-import button.primary{background:var(--teal);color:var(--white)}
    .supplier-import button:disabled{opacity:.5;cursor:wait}
    .supplier-import .import-totals{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;margin:16px 0}
    .supplier-import .import-totals div{padding:12px;background:var(--soft);border-radius:9px}
    .supplier-import .import-totals small,.supplier-import .import-totals strong{display:block}
    .supplier-import .import-issue{border-left:3px solid var(--teal);padding-left:12px;overflow-wrap:anywhere}
    .supplier-import .import-confirm{border:1px solid var(--line);border-radius:12px;padding:16px;margin:16px 0}
    .supplier-import p{line-height:1.5}
  `;
  document.head.append(style);

  function node(tag, text) {
    const element = document.createElement(tag);
    element.textContent = text;
    return element;
  }
  function button(label, handler, primary = false) {
    const element = node("button", label);
    element.type = "button";
    if (primary) element.className = "primary";
    element.onclick = handler;
    return element;
  }
  function money(value) {
    const amount = Number(value);
    return Number.isFinite(amount)
      ? amount.toLocaleString("ru-RU", {style: "currency", currency: "RUB"})
      : "Не определено";
  }
  function issueText(issue) {
    if (typeof issue === "string") return issue;
    if (!issue || typeof issue !== "object") return String(issue ?? "Ошибка проверки");
    const prefix = issue.row != null ? "Строка " + issue.row + " · " : "";
    let result = prefix + (issue.message || issue.error || "Требуется уточнение");
    if (Array.isArray(issue.suggestions) && issue.suggestions.length) {
      result += ". Варианты для сверки · " + issue.suggestions.map(item => {
        if (typeof item === "string") return item;
        return [item.code || item.article, item.name].filter(Boolean).join(" — ") || "Товар из каталога";
      }).join(", ");
    }
    return result;
  }
  async function post(path, payload) {
    const initData = window.Telegram?.WebApp?.initData;
    const response = await fetch(path, {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({...payload, ...(initData ? {initData} : {})}),
    });
    let result;
    try { result = await response.json(); } catch { result = {}; }
    if (!response.ok) {
      const message = response.status === 403
        ? "Проведение доступно пользователям с правом общего журнала."
        : response.status === 401
          ? "Переоткройте кабинет через Telegram, чтобы продолжить."
          : (typeof result.error === "string" ? result.error : "Не удалось выполнить операцию. Проверьте журнал перед повтором.");
      throw Error(message);
    }
    return result;
  }

  function mount(card) {
    if (card.querySelector(".supplier-import") || !/\.xlsx$/i.test(card.dataset.filename || "")) return;
    const record = Number(card.dataset.record);
    if (!Number.isSafeInteger(record) || record <= 0) return;
    const section = node("section", "");
    section.className = "supplier-import";
    const output = node("div", "");
    output.setAttribute("aria-live", "polite");
    const check = button("Проверить для МоегоСклада", preview);
    section.append(check, output);
    card.append(section);
    let pending = false;
    const mappings = {};

    async function preview() {
      if (pending) return;
      pending = true;
      check.disabled = true;
      output.replaceChildren(node("p", "Сверяем файл с каталогом МоегоСклада…"));
      try {
        const result = await post("/api/import/preview", {id: record, mappings});
        output.replaceChildren(node("h3", "Проверка отгрузки поставщика"));
        if (result.message) output.append(node("p", result.message));
        const totals = result.totals || {};
        const quantity = totals.quantity ?? result.rows?.reduce((sum, row) => sum + (Number(row.quantity ?? row.qty) || 0), 0);
        const grid = node("div", "");
        grid.className = "import-totals";
        for (const [label, value] of [
          ["Товаров, шт.", quantity == null ? "Не определено" : String(quantity)],
          ["Закупка", money(totals.purchases ?? totals.purchase)],
          ["Продажа", money(totals.sales ?? totals.revenue)],
          ["Валовая прибыль", money(totals.gross)],
        ]) {
          const cell = node("div", "");
          cell.append(node("small", label), node("strong", value));
          grid.append(cell);
        }
        output.append(grid);
        for (const warning of result.warnings || []) output.append(node("p", issueText(warning)));
        const errors = result.errors || [];
        if (errors.length) {
          output.append(node("p", "Уточните строки файла и загрузите исправленный документ."));
          const mappingForm = node("form", "");
          let mappingCount = 0;
          for (const error of errors) {
            const paragraph = node("p", issueText(error));
            paragraph.className = "import-issue";
            output.append(paragraph);
            const rawName = error?.raw_name || error?.rawName || error?.name;
            if (!rawName || typeof rawName !== "string") continue;
            mappingCount++;
            const label = node("label", "Товар поставщика · " + rawName);
            label.style.display = "block";
            label.style.margin = "12px 0";
            const input = node("input", "");
            input.type = "text";
            input.placeholder = "Наш артикул, например A2S-DEMO-P001";
            input.value = mappings[rawName] || "";
            input.maxLength = 150;
            input.style.display = "block";
            input.style.width = "100%";
            input.style.padding = "10px";
            const listId = "supplier-map-" + record + "-" + mappingCount;
            const list = node("datalist", "");
            list.id = listId;
            input.setAttribute("list", listId);
            for (const candidate of error.suggestions || []) {
              if (!candidate || typeof candidate !== "object" || !candidate.code) continue;
              const option = node("option", candidate.name || candidate.code);
              option.value = candidate.code;
              list.append(option);
            }
            input.oninput = () => {
              if (input.value.trim()) mappings[rawName] = input.value.trim();
              else delete mappings[rawName];
            };
            label.append(input, list);
            mappingForm.append(label);
          }
          if (mappingCount) {
            const retry = node("button", "Проверить соответствия");
            retry.type = "submit";
            mappingForm.onsubmit = event => {event.preventDefault(); preview()};
            mappingForm.append(retry);
            output.append(mappingForm);
          }
          return;
        }
        output.append(node("p", "После подтверждения в МоёмСкладе будут созданы приход и отгрузка. Закупочная сумма увеличит обязательства перед поставщиком."));
        const ask = button("Провести приход и отгрузку", () => {
          ask.disabled = true;
          const confirmation = node("div", "");
          confirmation.className = "import-confirm";
          confirmation.append(node("p", "Подтвердите проведение документа. Закупка · " + money(totals.purchases ?? totals.purchase) + ". Продажа · " + money(totals.sales ?? totals.revenue) + "."));
          const submit = button("Подтвердить проведение", async () => {
            if (pending) return;
            pending = true;
            submit.disabled = true;
            cancel.disabled = true;
            try {
              const payload = {id: record, mappings};
              if (result.confirmation_token) payload.confirmation_token = result.confirmation_token;
              if (result.digest) payload.digest = result.digest;
              const posted = await post("/api/import/execute", payload);
              confirmation.replaceChildren(node("p", posted.message || "Документы обработаны. Проверьте результат в МоёмСкладе."));
              for (const type of ["receipts", "demands", "documents"]) {
                if (!Array.isArray(posted[type])) continue;
                for (const document of posted[type]) {
                  const text = typeof document === "string" ? document : [document.type, document.name, document.id].filter(Boolean).join(" · ");
                  confirmation.append(node("p", text));
                }
              }
            } catch (error) {
              confirmation.append(node("p", error.message));
              submit.disabled = false;
              cancel.disabled = false;
            } finally { pending = false; }
          }, true);
          const cancel = button("Отмена", () => { confirmation.remove(); ask.disabled = false; });
          confirmation.append(submit, cancel);
          output.append(confirmation);
        }, true);
        output.append(ask);
      } catch (error) { output.replaceChildren(node("p", error.message)); }
      finally { pending = false; check.disabled = false; }
    }
  }
  function scan() {
    for (const card of journal.querySelectorAll("article[data-record]")) mount(card);
  }
  new MutationObserver(scan).observe(journal, {childList: true, subtree: true});
  scan();
})();
