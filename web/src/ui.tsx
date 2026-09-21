import { ArrowFillButton } from "@/components/obsidian/arrow-fill-button";
import { JellyLoader } from "@/components/obsidian/jelly-loader";

/** Primary action, recoloured from the active Omarchy theme. */
export function Primary({ children, ...props }: any) {
  return (
    <ArrowFillButton
      as="button"
      bgColor="var(--accent)"
      textColor="var(--bg0)"
      fillBgColor="var(--bg0)"
      fillTextColor="var(--accent)"
      hoverFillBgColor="var(--bg0)"
      hoverFillTextColor="var(--accent)"
      {...props}
    >
      {children}
    </ArrowFillButton>
  );
}

/** Compact loading indicator in the active theme accent. */
export function Loader({ size = 1 }: { size?: number }) {
  const colors = Array.from({ length: 6 }, (_, i) => `color-mix(in srgb, var(--accent) ${100 - i * 14}%, var(--bg0))`);
  return (
    <div className="jelly" style={{ ["--s" as any]: size }} aria-label="loading">
      <JellyLoader numberOfCubes={6} colors={colors} />
    </div>
  );
}

export const esc = (v: unknown) => String(v ?? "");
