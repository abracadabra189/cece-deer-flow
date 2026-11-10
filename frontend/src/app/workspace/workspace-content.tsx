import { cookies } from "next/headers";
import type { CSSProperties } from "react";
import { Toaster } from "sonner";

import { QueryClientProvider } from "@/components/query-client-provider";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { CeceMateTheme } from "@/components/workspace/cecemate/cecemate-theme";
import { CommandPalette } from "@/components/workspace/command-palette";
import { GatewayOfflineBanner } from "@/components/workspace/gateway-offline-banner";
import { ModelLoadErrorBanner } from "@/components/workspace/model-load-error-banner";
import { SettingsDialogHost } from "@/components/workspace/settings";
import { WorkspaceSettingsDeepLink } from "@/components/workspace/workspace-settings-deep-link";
import { WorkspaceSidebar } from "@/components/workspace/workspace-sidebar";
import { ExtensionPageBootstrap } from "@/core/extensions/hooks";
import { UserPreferencesBoundary } from "@/core/settings/user-preferences-boundary";

function parseSidebarOpenCookie(
  value: string | undefined,
): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}

export async function WorkspaceContent({
  children,
  gatewayUnavailable = false,
}: Readonly<{
  children: React.ReactNode;
  gatewayUnavailable?: boolean;
}>) {
  const cookieStore = await cookies();
  const initialSidebarOpen = parseSidebarOpenCookie(
    cookieStore.get("sidebar_state")?.value,
  );

  return (
    <QueryClientProvider>
      <UserPreferencesBoundary>
        <ExtensionPageBootstrap />
        <SidebarProvider
          className="cecemate-theme h-screen"
          defaultOpen={initialSidebarOpen}
          style={
            {
              "--sidebar-width": "248px",
              "--sidebar-width-icon": "48px",
            } as CSSProperties
          }
        >
          <CeceMateTheme>
            <WorkspaceSidebar />
            <SidebarInset className="min-w-0 bg-[#f5f7fa]">
              <GatewayOfflineBanner gatewayUnavailable={gatewayUnavailable} />
              <ModelLoadErrorBanner gatewayUnavailable={gatewayUnavailable} />
              {children}
            </SidebarInset>
            <SettingsDialogHost />
          </CeceMateTheme>
        </SidebarProvider>
        <CommandPalette />
        <WorkspaceSettingsDeepLink />
        <Toaster position="top-center" />
      </UserPreferencesBoundary>
    </QueryClientProvider>
  );
}
