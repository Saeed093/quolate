import { cn } from "@/lib/utils";

const TEAL = "#12A594";

export function QuolateMark({
  size = 32,
  ink = "#14213D",
  className,
}: {
  size?: number;
  ink?: string;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 200 200"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={cn("shrink-0", className)}
      aria-hidden
    >
      <circle cx="100" cy="95" r="55" stroke={ink} strokeWidth="16" />
      <rect x="72" y="82" width="13" height="38" rx="3" fill={ink} />
      <rect x="93" y="68" width="13" height="52" rx="3" fill={ink} />
      <rect x="114" y="98" width="13" height="22" rx="3" fill={TEAL} />
      <line
        x1="126"
        y1="130"
        x2="168"
        y2="168"
        stroke={TEAL}
        strokeWidth="16"
        strokeLinecap="round"
      />
    </svg>
  );
}
