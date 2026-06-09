import { motion } from 'framer-motion';
import type { LucideIcon } from 'lucide-react';

type NavItemProps = {
  icon: LucideIcon;
  label: string;
  active?: boolean;
};

export function NavItem({ icon: Icon, label, active = false }: NavItemProps) {
  return (
    <motion.button
      type="button"
      whileHover={{ y: -1, scale: 1.01 }}
      whileTap={{ scale: 0.99 }}
      transition={{ duration: 0.2, ease: 'easeOut' }}
      className={[
        'group relative flex w-full items-center gap-3 rounded-2xl px-4 py-3 text-sm font-medium transition-all duration-200',
        active
          ? 'bg-white/80 text-blue-600 shadow-sm ring-1 ring-white/60'
          : 'text-slate-600 hover:bg-white/60 hover:text-slate-950',
      ].join(' ')}
    >
      {active && (
        <motion.span
          layoutId="active-nav-indicator"
          className="absolute left-2 h-5 w-1 rounded-full bg-blue-500"
          transition={{ duration: 0.25, ease: 'easeOut' }}
        />
      )}
      <Icon className="ml-1 h-4 w-4" strokeWidth={1.8} />
      <span>{label}</span>
    </motion.button>
  );
}
