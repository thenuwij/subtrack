import Link from 'next/link'

export function PublicFooter() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-6xl flex-col gap-4 px-5 py-8 text-xs text-muted-foreground sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <p>© 2026 Subtrack. Spending information, not financial advice.</p>
        <nav className="flex gap-5" aria-label="Legal">
          <Link className="hover:text-foreground" href="/privacy">Privacy</Link>
          <Link className="hover:text-foreground" href="/terms">Terms</Link>
          <Link className="hover:text-foreground" href="/login">Sign in</Link>
        </nav>
      </div>
    </footer>
  )
}
