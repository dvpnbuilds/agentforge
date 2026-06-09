import type { ReactNode } from 'react';
import { Sidebar } from './Sidebar';
import { Topbar } from './Topbar';

type DashboardLayoutProps = {
  children?: ReactNode;
};

export function DashboardLayout({ children }: DashboardLayoutProps) {
  return (
    <div className="relative min-h-screen overflow-hidden bg-white text-slate-950">
      <div className="pointer-events-none absolute -left-36 top-10 h-96 w-96 rounded-full bg-blue-200/35 blur-3xl" />
      <div className="pointer-events-none absolute right-[-10rem] top-28 h-[30rem] w-[30rem] rounded-full bg-purple-200/35 blur-3xl" />
      <div className="pointer-events-none absolute bottom-[-14rem] left-1/3 h-[28rem] w-[28rem] rounded-full bg-sky-100/50 blur-3xl" />
      <div className="pointer-events-none absolute inset-0 opacity-[0.025] [background-image:radial-gradient(#0f172a_1px,transparent_1px)] [background-size:18px_18px]" />

      <Sidebar />

      <div className="relative z-0 min-h-screen pl-[328px] pr-6 pt-6">
        <Topbar />
        <main className="p-8">{children}</main>
      </div>
    </div>
  );
}
