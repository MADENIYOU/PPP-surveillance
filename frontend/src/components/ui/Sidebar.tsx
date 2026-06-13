import { NavLink, useLocation } from "react-router-dom";

const navItems = [
  { to: "/", icon: "◉", label: "Tableau de bord" },
  { to: "/map", icon: "◌", label: "Carte interactive" },
  { to: "/predictions", icon: "↗", label: "Prédictions" },
  { to: "/alerts", icon: "⚠", label: "Alertes" },
  { to: "/sensors", icon: "⬡", label: "Capteurs" },
  { to: "/reports", icon: "✎", label: "Signalements" },
  { to: "/compare", icon: "≣", label: "Comparer" },
  { to: "/about", icon: "ℹ", label: "À propos" },
];

export function Sidebar() {
  const location = useLocation();

  return (
    <aside className="hidden w-56 flex-shrink-0 flex-col border-r border-gray-800 bg-gray-900 md:flex">
      <div className="flex h-14 items-center gap-3 border-b border-gray-800 px-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-600 text-sm font-bold text-white">
          DA
        </div>
        <div>
          <p className="text-xs font-semibold text-white">Dakar Air</p>
          <p className="text-[10px] text-gray-500">Surveillance pollution</p>
        </div>
      </div>
      <nav className="flex-1 space-y-0.5 overflow-y-auto p-2">
        {navItems.map((item) => {
          const isActive = item.to === "/"
            ? location.pathname === "/"
            : location.pathname.startsWith(item.to);
          return (
            <NavLink
              key={item.to}
              to={item.to}
              className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ${
                isActive
                  ? "bg-emerald-600/20 text-emerald-400 font-medium"
                  : "text-gray-400 hover:bg-gray-800 hover:text-gray-200"
              }`}
            >
              <span className="text-base">{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </nav>
      <div className="border-t border-gray-800 p-3">
        <div className="rounded-lg bg-emerald-600/10 px-3 py-2 text-[11px] text-emerald-400">
          <p className="font-semibold">IQA actuel Dakar</p>
          <p className="mt-1 text-lg font-bold">—</p>
        </div>
      </div>
    </aside>
  );
}
