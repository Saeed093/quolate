import { cn } from "@/lib/utils";
import { QuolateMark } from "./QuolateMark";

const VARIANTS = {
  dark: {
    ink: "#F2F4F0",
    text: "text-paper",
    markSize: 32,
    fontSize: "text-base",
  },
  light: {
    ink: "#14213D",
    text: "text-ink",
    markSize: 48,
    fontSize: "text-3xl",
  },
  compact: {
    ink: "#F2F4F0",
    text: "text-paper",
    markSize: 28,
    fontSize: "text-sm",
  },
  sm: {
    ink: "#14213D",
    text: "text-ink",
    markSize: 28,
    fontSize: "text-sm",
  },
} as const;

export function QuolateLockup({
  variant = "dark",
  className,
}: {
  variant?: keyof typeof VARIANTS;
  className?: string;
}) {
  const v = VARIANTS[variant];

  return (
    <div className={cn("flex min-w-0 items-center gap-2.5", className)}>
      <QuolateMark size={v.markSize} ink={v.ink} />
      <span
        className={cn(
          "truncate font-display font-semibold tracking-tight",
          v.text,
          v.fontSize,
        )}
      >
        Quolate
      </span>
    </div>
  );
}
