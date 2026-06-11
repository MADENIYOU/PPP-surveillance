import { Link } from 'react-router-dom';

export function Header({ live }: { live?: React.ReactNode }) {
  return (
    <header className="flex items-center justify-between bg-slate-800 px-4 py-3 text-white">
      <Link to="/" className="text-lg font-bold">
        Surveillance Pollution Dakar
      </Link>
      <nav className="flex items-center gap-4 text-sm" aria-label="Navigation principale">
        <Link to="/report"
              className="rounded bg-orange-500 px-3 py-1.5 font-medium hover:bg-orange-600">
          Signaler
        </Link>
        <Link to="/about" className="hover:underline">
          À propos
        </Link>
        {live}
      </nav>
    </header>
  );
}
