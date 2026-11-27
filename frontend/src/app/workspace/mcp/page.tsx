import { PluginGallery } from "@/components/workspace/capabilities/plugin-gallery";
import { WorkspaceSidebarTrigger } from "@/components/workspace/workspace-sidebar-trigger";

export default function MCPServicesPage() {
  return (
    <main className="h-full overflow-y-auto bg-white px-6 py-5">
      <header className="mb-6 flex items-center gap-2">
        <WorkspaceSidebarTrigger className="md:hidden" />
        <h1 className="text-xl font-semibold">MCP服务</h1>
      </header>
      <PluginGallery query="" />
    </main>
  );
}
