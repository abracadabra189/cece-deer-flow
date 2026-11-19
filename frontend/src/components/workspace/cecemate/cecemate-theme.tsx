import { cn } from "@/lib/utils";

export function CeceMateTheme({
  children,
  className,
}: Readonly<{
  children: React.ReactNode;
  className?: string;
}>) {
  return (
    <div
      className={cn("cecemate-theme flex min-h-0 flex-1", className)}
      data-testid="cecemate-theme"
    >
      {children}
    </div>
  );
}
