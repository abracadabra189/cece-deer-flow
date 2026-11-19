import { type LucideIcon } from "lucide-react";

import { SidebarMenuButton, SidebarMenuItem } from "@/components/ui/sidebar";

export function CeceMateBetaItem({
  icon: Icon,
  label,
}: Readonly<{
  icon?: LucideIcon;
  label: string;
}>) {
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        aria-label={`${label} Beta`}
        aria-disabled="true"
        disabled
        className="h-[30px] cursor-not-allowed rounded-lg px-2.5 text-[13px] text-[#8a94a6] hover:bg-[#f7f8fc] hover:text-[#8a94a6]"
      >
        {Icon ? <Icon /> : null}
        <span>{label}</span>
        <span className="ml-auto rounded bg-[#f0ecff] px-1.5 py-0.5 text-[9px] leading-none text-[#8a7be0]">
          Beta
        </span>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
}
