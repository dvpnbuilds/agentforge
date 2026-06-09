import { Search } from 'lucide-react';

export function SearchBar() {
  return (
    <div className="relative hidden w-full max-w-md items-center md:flex">
      <Search className="pointer-events-none absolute left-4 h-4 w-4 text-slate-400" strokeWidth={1.8} />
      <input
        aria-label="Search"
        placeholder="Search anything..."
        className="h-12 w-full rounded-full border border-white/50 bg-white/60 pl-11 pr-5 text-sm text-slate-700 shadow-[0_8px_32px_rgba(0,0,0,0.05)] outline-none backdrop-blur-xl transition-all duration-200 placeholder:text-slate-400 focus:bg-white/80 focus:ring-2 focus:ring-blue-100"
      />
    </div>
  );
}
