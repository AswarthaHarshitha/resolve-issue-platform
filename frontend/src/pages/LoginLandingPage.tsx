import { Link } from "react-router-dom";

interface RoleCard {
  href: string;
  emoji: string;
  label: string;
  blurb: string;
  cta: string;
}

const ROLE_CARDS: RoleCard[] = [
  {
    href: "/student-login",
    emoji: "🎓",
    label: "Student",
    blurb: "Report and track issues",
    cta: "Student Login",
  },
  {
    href: "/resolver-login",
    emoji: "🛠",
    label: "Resolver",
    blurb: "Resolve issues for your team",
    cta: "Resolver Login",
  },
  {
    href: "/admin-login",
    emoji: "⚙",
    label: "Administrator",
    blurb: "Manage the platform",
    cta: "Admin Login",
  },
];

export function LoginLandingPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-12">
      <div className="mb-10 text-center">
        <h1 className="text-2xl font-semibold text-text-primary">Resolve</h1>
        <p className="mt-1 text-sm text-text-secondary">Intelligent Issue Resolution</p>
        <p className="mt-6 text-base font-medium text-text-primary">How are you signing in?</p>
      </div>

      <div className="grid w-full max-w-3xl grid-cols-1 gap-4 sm:grid-cols-3">
        {ROLE_CARDS.map((card) => (
          <Link
            key={card.href}
            to={card.href}
            className="flex flex-col items-center rounded-lg border border-border bg-surface p-6 text-center shadow-sm transition hover:border-accent hover:shadow-md"
          >
            <span className="text-3xl" aria-hidden="true">
              {card.emoji}
            </span>
            <span className="mt-3 text-base font-semibold text-text-primary">{card.label}</span>
            <span className="mt-1 text-sm text-text-secondary">{card.blurb}</span>
            <span className="mt-5 w-full rounded-md bg-accent px-4 py-2 text-sm font-medium text-surface transition group-hover:opacity-90">
              {card.cta}
            </span>
          </Link>
        ))}
      </div>

      <p className="mt-8 text-center text-sm text-text-secondary">
        Don&apos;t have an account?{" "}
        <Link to="/register" className="font-medium text-accent hover:underline">
          Register as a student
        </Link>
      </p>
    </div>
  );
}
