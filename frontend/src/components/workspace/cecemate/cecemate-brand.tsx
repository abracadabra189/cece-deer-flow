export function CeceMateLogo({ className }: { className?: string }) {
  return (
    <svg
      aria-hidden="true"
      className={className}
      fill="none"
      viewBox="0 0 48 48"
    >
      <defs>
        <linearGradient id="cecemate-logo" x1="0" x2="1" y1="0" y2="1">
          <stop offset="0" stopColor="#2563eb" />
          <stop offset="1" stopColor="#7b5cff" />
        </linearGradient>
      </defs>
      <rect
        x="3"
        y="3"
        width="42"
        height="42"
        rx="12"
        fill="url(#cecemate-logo)"
      />
      <path
        d="M14 18c0-3 2.4-5 5.5-5 2.6 0 4.7 1.4 5.3 3.6l-3.4 1c-.3-1-1-1.6-2-1.6-1.3 0-2.2.9-2.2 2.4v7.2c0 1.5.9 2.4 2.2 2.4 1 0 1.7-.6 2-1.6l3.4 1c-.6 2.2-2.7 3.6-5.3 3.6-3.1 0-5.5-2-5.5-5z"
        fill="#fff"
      />
      <circle cx="33.5" cy="24" r="4" fill="#fff" opacity=".9" />
    </svg>
  );
}

export function CeceMateBrand() {
  return (
    <div className="flex min-w-0 items-center gap-2.5 px-2">
      <CeceMateLogo className="size-7 shrink-0" />
      <span className="min-w-0 leading-tight">
        <span className="block truncate text-sm font-bold tracking-[0.02em]">
          CeCeMate
        </span>
        <span className="block truncate text-[10px] text-[#8a94a6]">
          创投洞察 · 智能体工作台
        </span>
      </span>
    </div>
  );
}
