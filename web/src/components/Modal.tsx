/**
 * The site's dialog shell (ADR-106; shared since ADR-111): native `<dialog>` with
 * `showModal()`, as the player card uses — focus trapping, Escape and an inert page come from
 * the platform. Opened when it mounts, closed when it unmounts, and focus goes back to whatever
 * opened it. My Leagues' editors, the board's player search and Start/Sit's add-player picker
 * all use it, so there is one dialog behaviour on the site rather than one per tab.
 */

import { useEffect, useId, useRef } from "react";

export function Modal({
  title,
  onClose,
  children,
  wide = false,
  picker = false,
}: {
  readonly title: string;
  readonly onClose: () => void;
  readonly children: React.ReactNode;
  readonly wide?: boolean;
  /**
   * A search dialog (ADR-111): on a phone it sits at the top of the screen rather than in the
   * middle, so the query and the first results stay above the on-screen keyboard.
   */
  readonly picker?: boolean;
}): React.JSX.Element {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (dialog === null) return;
    const active = document.activeElement;
    const returnTo = active instanceof HTMLElement && active !== document.body ? active : null;
    if (!dialog.open) dialog.showModal();
    // `showModal` focuses the first focusable control — the close button. A dialog opened for
    // one control (the player search, the league's name) marks it, and it gets focus instead.
    dialog.querySelector<HTMLElement>("[data-autofocus]")?.focus();
    return () => {
      if (dialog.open) dialog.close();
      if (returnTo?.isConnected === true) returnTo.focus();
    };
  }, []);

  return (
    <dialog
      ref={ref}
      className="lg-dialog"
      data-wide={wide || undefined}
      data-picker={picker || undefined}
      aria-labelledby={titleId}
      onClose={onClose}
      onClick={(event) => {
        // A click on the backdrop (the dialog element itself, outside its card) closes it.
        if (event.target === ref.current) onClose();
      }}
    >
      <div className="lg-dialog-card">
        <div className="lg-dialog-head">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="lg-dialog-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="lg-dialog-body">{children}</div>
      </div>
    </dialog>
  );
}
