import { Activity, Bell, UserCircle } from 'lucide-react';
import { motion } from 'framer-motion';
import { SearchBar } from '../ui/SearchBar';

const buttons = [
  { label: 'Notifications', icon: Bell },
  { label: 'Activity', icon: Activity },
  { label: 'Profile', icon: UserCircle },
];

export function Topbar() {
  return (
    <motion.header
      initial={{ y: -12, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.28, ease: 'easeOut' }}
      className="sticky top-6 z-10 flex h-20 items-center justify-between rounded-[1.75rem] border border-white/40 bg-white/60 px-6 shadow-[0_8px_32px_rgba(0,0,0,0.05)] backdrop-blur-xl"
    >
      <div className="min-w-[160px]">
        <h1 className="text-2xl font-semibold tracking-[-0.04em] text-slate-950">Dashboard</h1>
      </div>

      <SearchBar />

      <div className="flex items-center gap-2">
        {buttons.map(({ label, icon: Icon }) => (
          <motion.button
            key={label}
            type="button"
            aria-label={label}
            whileHover={{ scale: 1.02, y: -1 }}
            whileTap={{ scale: 0.98 }}
            transition={{ duration: 0.2 }}
            className="grid h-11 w-11 place-items-center rounded-full border border-white/50 bg-white/55 text-slate-500 shadow-[0_8px_32px_rgba(0,0,0,0.04)] backdrop-blur-xl transition hover:bg-white/85 hover:text-blue-600 hover:shadow-[0_10px_35px_rgba(37,99,235,0.10)]"
          >
            <Icon className="h-4 w-4" strokeWidth={1.8} />
          </motion.button>
        ))}
      </div>
    </motion.header>
  );
}
