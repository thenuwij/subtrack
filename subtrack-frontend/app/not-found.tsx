import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Logo } from '@/components/layout/Logo'

export default function NotFound() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6 py-12 text-foreground">
      <div className="w-full max-w-md space-y-6 text-center">
        <div className="flex justify-center"><Logo /></div>
        <div className="space-y-2">
          <p className="text-sm font-medium text-primary">404</p>
          <h1 className="text-3xl font-semibold tracking-tight">Page not found</h1>
          <p className="text-sm text-muted-foreground">
            This page may have moved, or the address may be incorrect.
          </p>
        </div>
        <Button asChild>
          <Link href="/dashboard">Return to Subtrack</Link>
        </Button>
      </div>
    </main>
  )
}
