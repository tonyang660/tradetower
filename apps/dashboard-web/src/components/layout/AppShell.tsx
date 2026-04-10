import { ReactNode } from "react";
import Sidebar from "./Sidebar";

export default function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen bg-transparent text-white">
      <div className="flex min-h-screen">
        <Sidebar />
        <main className="flex-1">
          <div className="mx-auto max-w-[1600px] px-6 py-6 lg:px-8">{children}</div>
        </main>
      </div>
    </div>
  );
}
