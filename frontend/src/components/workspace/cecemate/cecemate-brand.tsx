import Image from "next/image";

export function CeceMateLogo({ className }: { className?: string }) {
  return (
    <Image
      alt="CeCeMate"
      className={className}
      height={64}
      sizes="62px"
      src="/images/welcome-greeting.png"
      width={64}
    />
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
