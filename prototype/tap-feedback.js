// Capture physical pointer clicks before the glass navigation forwards them.
document.addEventListener("click", (event) => {
  if (!event.isTrusted || event.detail === 0) return;

  const control = event.target.closest?.("button, a[href], summary");
  if (!control || control.disabled) return;

  if (document.activeElement === control) control.blur();
  if (!control.closest("#glass-root, main nav")) return;

  const app = window.Telegram?.WebApp;
  if (app?.isVersionAtLeast?.("6.1")) {
    app.HapticFeedback?.impactOccurred?.("light");
  }
}, true);
