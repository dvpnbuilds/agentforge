import { Bot, CheckSquare, Clock3, LayoutDashboard, Library, Settings, ChevronsUpDown } from 'lucide-react';
import { motion } from 'framer-motion';
import { NavItem } from '../ui/NavItem';
import logo from '../assets/logo.png';

const items = [
  { label: 'Dashboard', icon: LayoutDashboard, active: true },
  { label: 'Agents', icon: Bot },
  { label: 'Cron', icon: Clock3 },
  { label: 'Tasks', icon: CheckSquare },
  { label: 'Library', icon: Library },
];

export function Sidebar() {
  return (
    <motion.aside
      initial={{ x: -24, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      transition={{ duration: 0.3, ease: 'easeOut' }}
      className="fixed left-6 top-6 z-20 flex h-[calc(100vh-3rem)] w-[280px] flex-col rounded-[2rem] border border-white/40 bg-white/60 p-4 shadow-[0_8px_32px_rgba(0,0,0,0.05)] backdrop-blur-xl"
    >
      <div className="flex items-center gap-3 px-2 py-3">
        <div className="grid h-12 w-12 place-items-center overflow-hidden rounded-2xl border border-white/70 bg-white shadow-sm ring-1 ring-blue-100/60">
          <img src={logo} alt="AgentForge mascot" className="h-full w-full object-cover" />
        </div>
        <div>
          <div className="text-lg font-semibold tracking-[-0.03em] text-slate-950">AgentForge</div>
          <div className="text-xs font-medium text-slate-400">AI Operating System</div>
          <div className="mt-1 inline-flex items-center rounded-full border border-blue-100 bg-blue-50/80 px-2 py-0.5 text-[10px] font-semibold tracking-wide text-blue-600 shadow-sm">v1.1</div>
        </div>
      </div>

      <nav className="mt-8 space-y-2">
        {items.map((item) => (
          <NavItem key={item.label} {...item} />
        ))}
      </nav>

      <div className="mt-auto space-y-3 border-t border-white/50 pt-4">
        <NavItem icon={Settings} label="Settings" />

        <motion.button
          type="button"
          whileHover={{ scale: 1.02 }}
          transition={{ duration: 0.2 }}
          className="flex w-full items-center justify-between rounded-2xl border border-white/40 bg-white/45 px-4 py-3 text-left backdrop-blur-xl transition hover:bg-white/70"
        >
          <div>
            <div className="text-sm font-medium text-slate-800">Primary Workspace</div>
            <div className="text-xs text-slate-400">Production</div>
          </div>
          <ChevronsUpDown className="h-4 w-4 text-slate-400" />
        </motion.button>

        <div className="flex items-center gap-3 rounded-2xl bg-white/45 px-3 py-3">
          <div className="h-10 w-10 rounded-full bg-gradient-to-br from-blue-100 to-purple-100 ring-1 ring-white/80" />
          <div>
            <div className="text-sm font-semibold text-slate-900">Alex Builder</div>
            <div className="text-xs text-slate-400">Administrator</div>
          </div>
        </div>
      </div>
    </motion.aside>
  );
}
