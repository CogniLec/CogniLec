/**
 * Purely decorative ambient orbs behind the page content — the app's
 * "floating" visual signature. Fixed position, aria-hidden, and
 * pointer-events-none so it never affects layout, interaction, or
 * accessible-name queries (including in tests). Motion is disabled under
 * prefers-reduced-motion via index.css.
 */
export function FloatingBackdrop(): JSX.Element {
  return (
    <div aria-hidden="true" className="fixed inset-0 -z-10 overflow-hidden">
      <div
        className="float-orb -left-24 -top-24 h-72 w-72 bg-brand-600/20"
        style={{ animationDelay: "0s" }}
      />
      <div
        className="float-orb-alt right-[-6rem] top-1/3 h-96 w-96 bg-indigo-500/10"
        style={{ animationDelay: "-6s" }}
      />
      <div
        className="float-orb bottom-[-8rem] left-1/4 h-80 w-80 bg-brand-500/10"
        style={{ animationDelay: "-9s" }}
      />
    </div>
  );
}
