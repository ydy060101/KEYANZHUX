import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/cn";

const button = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-control font-medium " +
    "transition-[background-color,border-color,color,box-shadow] duration-[--dur-fast] ease-[--ease] " +
    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 " +
    "focus-visible:ring-offset-bg disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-primary text-white hover:opacity-90 active:opacity-80",
        secondary: "border border-border bg-surface text-ink hover:bg-surface-2 active:bg-surface-2",
        ghost: "text-ink-2 hover:bg-surface-2 hover:text-ink active:bg-surface-2",
        danger: "bg-danger text-white hover:opacity-90 active:opacity-80",
      },
      size: {
        sm: "h-8 px-3 text-[var(--text-sm)]",
        md: "h-9 px-4 text-[var(--text-base)]",
        lg: "h-11 px-6 text-[var(--text-md)]",
        icon: "size-9",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof button> {
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, loading = false, disabled, children, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(button({ variant, size }), className)}
      disabled={disabled ?? loading}
      aria-busy={loading || undefined}
      {...props}
    >
      {loading && <Loader2 className="size-4 animate-spin" aria-hidden />}
      {children}
    </button>
  ),
);
Button.displayName = "Button";
