import { Link, useLocation } from 'react-router-dom'

export function NavBar({ title }: { title: string }) {
  const location = useLocation()

  return (
    <nav className="shrink-0 border-b border-neutral-800 px-4 py-2 flex items-center justify-between bg-black gap-2">
      <Link
        to="/"
        className="text-[10px] text-neutral-500 hover:text-green-500 uppercase tracking-wider transition-colors whitespace-nowrap"
      >
        PolyEdge
      </Link>
      <span className="text-[10px] font-bold text-neutral-400 uppercase tracking-[0.2em] whitespace-nowrap hidden sm:inline">{title}</span>
      <div className="flex items-center gap-3 overflow-x-auto scrollbar-none">
        <Link
          to="/dashboard"
          className={`text-[10px] uppercase tracking-wider transition-colors whitespace-nowrap ${
            location.pathname === '/dashboard' ? 'text-green-500' : 'text-neutral-500 hover:text-green-500'
          }`}
        >
          Dashboard
        </Link>
        <Link
          to="/admin"
          className={`text-[10px] uppercase tracking-wider transition-colors whitespace-nowrap ${
            location.pathname === '/admin' ? 'text-green-500' : 'text-neutral-500 hover:text-green-500'
          }`}
        >
          Admin
        </Link>
        <Link
          to="/mirofish"
          className={`text-[10px] uppercase tracking-wider transition-colors whitespace-nowrap ${
            location.pathname === '/mirofish' ? 'text-green-500' : 'text-neutral-500 hover:text-green-500'
          }`}
        >
          MiroFish
        </Link>
        <Link
          to="/livestream"
          className={`text-[10px] uppercase tracking-wider transition-colors whitespace-nowrap ${
            location.pathname === '/livestream' ? 'text-green-500' : 'text-neutral-500 hover:text-green-500'
          }`}
        >
          LiveStream
        </Link>
        <Link
          to="/journal"
          className={`text-[10px] uppercase tracking-wider transition-colors whitespace-nowrap ${
            location.pathname === '/journal' ? 'text-green-500' : 'text-neutral-500 hover:text-green-500'
          }`}
        >
          Journal
        </Link>
        <a
          href="/docs/"
          className="text-[10px] uppercase tracking-wider transition-colors text-neutral-500 hover:text-green-500 whitespace-nowrap"
        >
          Docs
        </a>
      </div>
    </nav>
  )
}
