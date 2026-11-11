(() => {
  const main = document.querySelector("main");
  const mobileMenu = main.querySelector("nav");
  const sidebar = document.createElement("aside");
  sidebar.className = "workspace-sidebar";

  const logo = document.createElement("a");
  logo.href = "#";
  logo.className = "workspace-logo";
  logo.setAttribute("aria-label", "ТОВАРНО — сводка");
  for (const image of main.querySelectorAll("header .brand-logo")) logo.append(image.cloneNode());
  logo.addEventListener("click", () => activate(0));
  sidebar.append(logo);

  const links = document.createElement("div");
  links.className = "workspace-links";
  links.setAttribute("role", "navigation");
  links.setAttribute("aria-label", "Разделы кабинета");
  sidebar.append(links);

  function activate(index) {
    if (location.hash) location.hash = "";
    requestAnimationFrame(() => {
      mobileMenu.querySelector('[data-index="' + index + '"]')?.click();
      window.dispatchEvent(new Event("resize"));
    });
  }

  for (const original of mobileMenu.querySelectorAll("button[data-index]")) {
    const button = document.createElement("button");
    button.type = "button";
    button.innerHTML = original.innerHTML;
    button.dataset.section = original.dataset.index;
    button.addEventListener("click", () => activate(button.dataset.section));
    links.append(button);
  }

  const documents = document.createElement("div");
  documents.className = "workspace-documents";
  const documentLinks = [
    ["#partner", "Склад партнёра", "M3 9l9-5 9 5v11H3z M7 20v-7h10v7"],
    ["#upload", "Загрузить документ", "M12 16V3 M7 8l5-5 5 5 M4 15v6h16v-6"],
    ["#journal", "Журнал загрузок", "M5 3h10l4 4v14H5z M14 3v5h5 M8 12h8 M8 16h6"]
  ];
  for (const [fragment, label, path] of documentLinks) {
    const anchor = document.createElement("a");
    anchor.href = fragment;
    anchor.innerHTML = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="' + path + '"/></svg>';
    anchor.append(document.createTextNode(label));
    documents.append(anchor);
  }
  links.append(documents);
  main.prepend(sidebar);

  function update() {
    const current = ["#partner","#journal","#upload"].includes(location.hash) ? null : mobileMenu.querySelector(".on")?.dataset.index;
    for (const button of links.querySelectorAll("button")) {
      button.setAttribute("aria-current", button.dataset.section === current ? "page" : "false");
    }
    for (const anchor of documents.querySelectorAll("a")) {
      anchor.setAttribute("aria-current", anchor.hash === location.hash ? "page" : "false");
    }
  }
  new MutationObserver(update).observe(mobileMenu, {childList:true, subtree:true, attributes:true, attributeFilter:["class"]});
  window.addEventListener("hashchange", update);
  update();
  // The chart measures its canvas width when it renders.
  window.dispatchEvent(new Event("resize"));
})();
