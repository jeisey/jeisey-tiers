/**
 * Copy text for a reader (ADR-116): the async Clipboard API where the page may use it, then the
 * selection-based fallback older and stricter browsers still allow. Resolves false when neither
 * worked, so the page can say so and show the text to copy by hand — never a silent no-op.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (typeof navigator !== "undefined" && typeof navigator.clipboard?.writeText === "function") {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Permission refused or an insecure context: try the fallback.
  }
  try {
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "0";
    area.style.left = "0";
    area.style.opacity = "0";
    document.body.append(area);
    const active = document.activeElement;
    area.select();
    // Deprecated but still the only copy path where the async Clipboard API is refused (an
    // insecure context, an older WebView); used only after that API failed or is absent.
    // eslint-disable-next-line @typescript-eslint/no-deprecated
    const copied = typeof document.execCommand === "function" && document.execCommand("copy");
    area.remove();
    if (active instanceof HTMLElement) active.focus();
    return copied;
  } catch {
    return false;
  }
}
